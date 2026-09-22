"""
One HTTPS connection, kept open, for the two remote stages.

Why: ``urllib.request`` cannot do this. Its ``AbstractHTTPHandler.do_open``
hard-sets ``Connection: close`` and then closes the socket itself, so every call
pays a fresh TCP handshake plus a TLS handshake. That is two round trips — about
50-75 ms to a European pod — and with STREAMING_PARTIALS on we make roughly two
calls a second, one for transcription and one for translation. It is ~10% of the
delay between someone speaking and the words appearing, spent re-introducing
ourselves to a machine we were talking to a moment ago.

Written once and shared by asr_remote.py and mt_remote.py rather than twice,
because the interesting part is not the connection, it is the retry — and the
retry has a failure mode that would reach the projector:

    A connection that has been idle for a while may already have been closed by
    the server or by RunPod's proxy without us noticing. The next request is
    written into a socket that is half dead, and surfaces as RemoteDisconnected
    or BadStatusLine when we try to read the reply. That is NOT the server being
    unhealthy — it is normal, expected, and invisible with connection-per-
    request. So we reconnect and send it again, once.

    Crucially, that retry must be invisible to the caller. Both callers count
    consecutive failures and fall back to this laptop's much weaker models after
    two of them (REMOTE_ASR_FAILURES_BEFORE_FALLBACK). If a routine idle-socket
    recycle counted as a failure, a quiet moment in the khutbah would drop the
    whole rest of the sermon onto the laptop to save 60 ms — strictly worse than
    not doing this at all.

Retrying a POST is safe here specifically because both endpoints are pure
functions: /transcribe and /translate compute an answer and change nothing. A
duplicate that did arrive costs a little GPU time and nothing else.
"""

from __future__ import annotations

import http.client
import socket
import urllib.error
import urllib.parse

# Failures that mean "this socket was stale", as opposed to "the server is
# unhappy". Only these are retried, and only once.
_STALE = (
    http.client.RemoteDisconnected,
    http.client.BadStatusLine,
    http.client.CannotSendRequest,
    http.client.ResponseNotReady,
    ConnectionResetError,
    BrokenPipeError,
)


class KeepAliveClient:
    """A persistent connection to one host, reconnecting as needed.

    Not thread-safe, which is fine and deliberate: app.py runs a single
    ``asr-mt`` worker, so there is never more than one request in flight. Each
    caller owns its own client.
    """

    def __init__(self, base_url: str):
        parts = urllib.parse.urlsplit(base_url)
        self._https = parts.scheme != "http"       # direct-TCP fallback is plain
        self._host = parts.hostname or ""
        self._port = parts.port
        self._prefix = parts.path.rstrip("/")
        self._conn: http.client.HTTPConnection | None = None

    # -- internals ---------------------------------------------------------

    def _connect(self, timeout: float):
        cls = http.client.HTTPSConnection if self._https else http.client.HTTPConnection
        self._conn = cls(self._host, self._port, timeout=timeout)

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _attempt(self, method, path, body, headers, timeout) -> bytes:
        if self._conn is None:
            self._connect(timeout)
        else:
            # The timeout differs between finals and partials, and a connection
            # built for one must not silently impose it on the other.
            self._conn.timeout = timeout
            if self._conn.sock is not None:
                self._conn.sock.settimeout(timeout)

        self._conn.request(method, f"{self._prefix}{path}", body=body, headers=headers)
        resp = self._conn.getresponse()
        # ALWAYS read the body, including on an error status. An unread body
        # leaves the connection out of step, and every later request on it
        # fails in a way that looks like the server has gone mad.
        payload = resp.read()

        if resp.status != 200:
            self.close()        # don't keep a connection we just upset
            # Raise the same exception type urllib would have, so both callers'
            # existing except-clauses and error messages keep working unchanged.
            raise urllib.error.HTTPError(
                f"{self._host}{path}", resp.status, resp.reason, resp.headers, None
            )

        # The server may still have asked to close (HTTP/1.0, or a proxy hop).
        if resp.will_close:
            self.close()
        return payload

    # -- public ------------------------------------------------------------

    def post(self, path: str, body: bytes, headers: dict, timeout: float) -> bytes:
        """POST and return the raw response body. Raises on real failure."""
        try:
            return self._attempt("POST", path, body, headers, timeout)
        except _STALE:
            # Stale socket: reconnect and try once more. Deliberately NOT
            # reported to the caller — see the module docstring.
            self.close()
        except socket.timeout:
            # A timeout is a real signal about the server, not about the socket.
            # Drop the connection (we do not know what state it is in) but let
            # the caller count it.
            self.close()
            raise

        return self._attempt("POST", path, body, headers, timeout)
