"""
Make Tkinter find its Tcl library on Windows.

Tkinter draws the subtitle window, so when it cannot start, nothing works. The
failure is:

    _tkinter.TclError: Can't find a usable init.tcl in the following
    directories: .../Python313/lib/tcl8.6 ...

Note what it is looking for: ``<prefix>/lib/tcl8.6``, the Unix layout. The
Windows Python installer puts those files in ``<prefix>/tcl/tcl8.6`` instead,
and Tcl normally locates them from the DLL's own path. That fails in two
ordinary situations:

  * inside a virtual environment, where sys.prefix is the venv and the Tcl
    files are back in the base installation; and
  * when some unrelated software has left TCL_LIBRARY pointing somewhere else.

The fix is to say where they are. Tcl reads TCL_LIBRARY and TK_LIBRARY, so if
the directories exist under the base installation and the variables are not
already set correctly, we set them.

Imported by subtitles/__init__.py so it runs before anything can touch
tkinter — a fix applied after the import is a fix applied too late.
"""

import os
import sys


def ensure_tcl() -> str | None:
    """Point TCL_LIBRARY/TK_LIBRARY at the real files. Returns what it did."""
    if os.name != "nt":
        return None

    # sys.base_prefix is the real Python install; sys.prefix is the venv.
    # Check both, base first, plus the DLL directory's parent for unusual
    # layouts.
    roots = []
    for r in (getattr(sys, "base_prefix", None), sys.prefix,
              os.path.dirname(os.path.dirname(getattr(sys, "_base_executable", "") or ""))):
        if r and r not in roots:
            roots.append(r)

    def usable(path):
        return path and os.path.isfile(os.path.join(path, "init.tcl"))

    # An existing setting that actually works is left alone; one that does not
    # is worse than nothing, because it stops Tcl looking anywhere else.
    if usable(os.environ.get("TCL_LIBRARY")):
        return None

    for root in roots:
        tcl_dir = os.path.join(root, "tcl")
        if not os.path.isdir(tcl_dir):
            continue
        # tcl8.6, tcl8.7, ... — take whatever is actually there.
        for name in sorted(os.listdir(tcl_dir), reverse=True):
            cand = os.path.join(tcl_dir, name)
            if name.startswith("tcl") and usable(cand):
                os.environ["TCL_LIBRARY"] = cand
                tk = os.path.join(tcl_dir, name.replace("tcl", "tk", 1))
                if os.path.isdir(tk):
                    os.environ["TK_LIBRARY"] = tk
                return cand
    return None


def tcl_report() -> str:
    """Where things stand, for when it still does not work."""
    lines = [f"  sys.prefix      : {sys.prefix}",
             f"  sys.base_prefix : {getattr(sys, 'base_prefix', '?')}",
             f"  TCL_LIBRARY     : {os.environ.get('TCL_LIBRARY') or '(not set)'}",
             f"  TK_LIBRARY      : {os.environ.get('TK_LIBRARY') or '(not set)'}"]
    for root in {getattr(sys, "base_prefix", ""), sys.prefix}:
        if not root:
            continue
        d = os.path.join(root, "tcl")
        lines.append(f"  {d}: "
                     + ("exists -> " + ", ".join(sorted(os.listdir(d))[:6])
                        if os.path.isdir(d) else "MISSING"))
    return "\n".join(lines)
