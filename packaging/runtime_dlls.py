"""Put the frozen Qt and Shiboken DLL directories on Windows' loader path."""

import os
import sys
import time

# The first application runtime hook runs before main's heavy Qt imports.
sys._camfloat_started_at = time.perf_counter()

from pathlib import Path


_dll_directory_handles = []

if sys.platform == "win32" and getattr(sys, "_MEIPASS", None):
    bundle = Path(sys._MEIPASS)
    for child in ("shiboken6", "PySide6"):
        directory = bundle / child
        if directory.is_dir():
            os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                _dll_directory_handles.append(os.add_dll_directory(str(directory)))
