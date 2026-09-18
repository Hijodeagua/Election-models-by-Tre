"""UTF-8 console output for the CLI scripts.

Every script in here prints box-drawing dividers, en dashes and arrows. On
Windows, Python picks the ANSI code page (cp1252) for stdout whenever output is
*not* a terminal — which is exactly what ``| Tee-Object`` or ``> run.log`` does.
The result is a UnicodeEncodeError partway through a report: a 70-minute
training run that reached its verdict and then died printing the header.

``enable_utf8_output()`` makes the streams UTF-8, makes any remaining encoding
problem non-fatal, and asks the Windows console to render UTF-8 so the output
is readable rather than mojibake. It is a no-op everywhere else.
"""

from __future__ import annotations

import contextlib
import sys


def enable_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr and stop encoding errors killing a run."""
    for stream in (sys.stdout, sys.stderr):
        # reconfigure() mutates the existing wrapper, so logging handlers that
        # already captured the stream pick this up too.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(ValueError, OSError):  # detached/non-text stream
            reconfigure(encoding="utf-8", errors="replace")

    if sys.platform == "win32":
        with contextlib.suppress(AttributeError, OSError, ImportError):
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)  # cp65001 = UTF-8
