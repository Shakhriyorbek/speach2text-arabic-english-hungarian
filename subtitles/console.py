"""
Make the Windows console safe for printing Hungarian text.

The default Windows console code page (cp1252) cannot encode characters like
'ő' / 'ű', so a plain print() of Hungarian raises UnicodeEncodeError and can
crash the program. Calling ``enable_utf8_console()`` once at startup switches
stdout/stderr to UTF-8 (replacing anything still unencodable rather than
crashing). This only affects console text — the Tkinter subtitle window renders
Unicode fine regardless.
"""

import sys


def enable_utf8_console():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
