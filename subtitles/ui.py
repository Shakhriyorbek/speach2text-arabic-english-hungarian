"""
Fullscreen subtitle window (Tkinter, standard library only).

Shows the most recent Hungarian subtitle lines large and centred on a black
background, suitable for projecting. The newest line is bright; older lines are
dimmed. A small badge in the top-right shows the current mode and status.

Threading rule: Tkinter is not thread-safe. This window runs on the MAIN
thread and pulls finished lines from a queue via a periodic ``after`` poll.
Worker threads must NEVER call Tkinter directly — they only put strings on the
queue.

The window drives the rest of the app through a small set of callbacks passed
to ``__init__`` (set_mode, toggle_pause, on_quit). This keeps ui.py ignorant of
the ASR/audio internals.
"""

import queue
import tkinter as tk
import tkinter.font as tkfont

import config


class SubtitleWindow:
    def __init__(
        self,
        ui_queue: "queue.Queue",
        on_set_mode,          # callable(mode: str) -> None    ("part1"/"part2")
        on_toggle_pause,      # callable() -> bool  (returns new paused state)
        on_quit,              # callable() -> None
    ):
        self.ui_queue = ui_queue
        self._on_set_mode = on_set_mode
        self._on_toggle_pause = on_toggle_pause
        self._on_quit = on_quit

        self.root = tk.Tk()
        self.root.title("Khutbah Subtitles")
        self.root.configure(bg=config.BG)

        self._font_size = config.FONT_SIZE
        self._font = tkfont.Font(family=config.FONT_FAMILY, size=self._font_size)
        self._badge_font = tkfont.Font(family=config.FONT_FAMILY, size=16)

        self._mode = "part1"
        self._paused = False

        self._fullscreen = config.START_FULLSCREEN
        self.root.attributes("-fullscreen", self._fullscreen)

        # --- badge (top-right) ---------------------------------------------
        self._badge = tk.Label(
            self.root, text="", font=self._badge_font,
            fg=config.FG_BADGE, bg=config.BG, anchor="e", padx=16, pady=8,
        )
        self._badge.pack(side="top", fill="x")

        # --- subtitle lines (centre) ---------------------------------------
        self._lines_frame = tk.Frame(self.root, bg=config.BG)
        self._lines_frame.pack(expand=True, fill="both")

        self._labels = []
        for _ in range(config.MAX_LINES):
            lbl = tk.Label(
                self._lines_frame, text="", font=self._font,
                fg=config.FG_OLD, bg=config.BG, justify="center", wraplength=1,
            )
            lbl.pack(expand=True)
            self._labels.append(lbl)

        # Backing store of the last N lines (each: (hu_text, en_text|None)).
        self._history = []
        # In-progress line from cloud-mode interim results ("" = none).
        self._partial = ""

        self._splash()
        self._bind_keys()
        self._update_badge()
        self._update_wraplength()
        self.root.bind("<Configure>", lambda e: self._update_wraplength())

        # Start polling the queue.
        self.root.after(100, self._poll_queue)

    # -- public --------------------------------------------------------------

    def run(self):
        """Enter the Tkinter main loop (blocks until quit)."""
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        self.root.mainloop()

    def flag_dropped(self):
        """Called (thread-safe via queue sentinel) to show the '…' overload mark."""
        # We route this through the queue as a sentinel; see _poll_queue.
        pass

    # -- setup helpers -------------------------------------------------------

    def _splash(self):
        self._history = [("Készen áll — F1: 1. rész (arab)   F2: 2. rész (angol)", None)]
        self._render()

    def _bind_keys(self):
        r = self.root
        r.bind("<F1>", lambda e: self._set_mode("part1"))
        r.bind("<F2>", lambda e: self._set_mode("part2"))
        r.bind("<F11>", lambda e: self._toggle_fullscreen())
        r.bind("<plus>", lambda e: self._change_font(+4))
        r.bind("<KP_Add>", lambda e: self._change_font(+4))
        r.bind("<equal>", lambda e: self._change_font(+4))   # '+' without shift
        r.bind("<minus>", lambda e: self._change_font(-4))
        r.bind("<KP_Subtract>", lambda e: self._change_font(-4))
        r.bind("<p>", lambda e: self._toggle_pause())
        r.bind("<P>", lambda e: self._toggle_pause())
        r.bind("<Escape>", lambda e: self._quit())

    # -- key actions ---------------------------------------------------------

    def _set_mode(self, mode):
        self._mode = mode
        self._on_set_mode(mode)
        self._update_badge()

    def _toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        self.root.attributes("-fullscreen", self._fullscreen)

    def _change_font(self, delta):
        self._font_size = max(12, self._font_size + delta)
        self._font.configure(size=self._font_size)
        self._update_wraplength()

    def _toggle_pause(self):
        self._paused = bool(self._on_toggle_pause())
        self._update_badge()

    def _quit(self):
        try:
            self._on_quit()
        finally:
            self.root.destroy()

    # -- rendering -----------------------------------------------------------

    def _update_wraplength(self):
        w = self.root.winfo_width()
        if w > 100:
            for lbl in self._labels:
                lbl.configure(wraplength=w - 80)

    def _update_badge(self):
        mode_txt = "1: ARAB" if self._mode == "part1" else "2: AUTO"
        status = ""
        if self._paused:
            status = "  ⏸ SZÜNET"
        self._badge.configure(text=f"{mode_txt}{status}")

    def _render(self):
        # Newest line last in history; show them top(old)->bottom(new).
        # An in-progress (interim) line, if any, hangs below as the newest — it
        # is replaced in place as the speaker continues, then promoted to
        # history when the final result arrives.
        rows = list(self._history)
        if self._partial:
            rows.append((self._partial, None))
        rows = rows[-config.MAX_LINES:]
        # Pad so the block stays vertically centred.
        pad = config.MAX_LINES - len(rows)

        idx = 0
        for _ in range(pad):
            self._labels[idx].configure(text="")
            idx += 1

        n = len(rows)
        for i, (hu, en) in enumerate(rows):
            is_newest = (i == n - 1)
            text = hu
            if config.SHOW_ENGLISH and en:
                text = f"{hu}\n[{en}]"
            self._labels[idx].configure(
                text=text,
                fg=config.FG_NEW if is_newest else config.FG_OLD,
            )
            idx += 1

    def _add_line(self, hu, en=None):
        self._partial = ""          # a final result supersedes any interim text
        self._history.append((hu, en))
        if len(self._history) > config.MAX_LINES:
            self._history = self._history[-config.MAX_LINES:]
        self._render()

    def _set_partial(self, hu):
        """Show/replace the in-progress line (cloud mode interim results)."""
        self._partial = hu
        self._render()

    # -- queue polling (main thread) ----------------------------------------

    def _poll_queue(self):
        try:
            while True:
                item = self.ui_queue.get_nowait()
                if item is None:
                    continue
                kind = item[0]
                if kind == "line":
                    _, hu, en = item
                    self._add_line(hu, en)
                elif kind == "partial":
                    self._set_partial(item[1])
                elif kind == "dropped":
                    # Briefly append an overload marker to the badge.
                    cur = self._badge.cget("text")
                    if "…" not in cur:
                        self._badge.configure(text=cur + "  …")
                        self.root.after(1500, self._update_badge)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)
