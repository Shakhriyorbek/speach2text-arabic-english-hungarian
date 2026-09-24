# Applied at import time, before anything can touch tkinter: on Windows the
# Tcl library often cannot be found from inside a virtual environment, and a
# fix applied later is a fix applied too late. No effect on other platforms.
from subtitles.winfix import ensure_tcl as _ensure_tcl

_ensure_tcl()
