# Third-party components

CamFloat uses the following unmodified runtime components. License texts are in `licenses/`.

| Component | Version | Project / license |
| --- | --- | --- |
| CPython | 3.14.4 | https://www.python.org/ · Python license, including bundled third-party notices |
| PySide6 / Shiboken6 / Qt | 6.12.0 | https://www.qt.io/qt-for-python · LGPL-3.0 / GPL alternatives described in package metadata |
| python-vlc | 3.0.21203 | https://github.com/oaubert/python-vlc · LGPL-2.1-or-later |
| PyInstaller bootloader | 6.22.3 | https://pyinstaller.org/ · GPL with the bootloader distribution exception |

Qt and Python runtime DLLs are distributed as separate files in `_internal/`; replacement of these libraries is not restricted by CamFloat. Corresponding upstream sources and notices:

- Qt for Python: https://code.qt.io/cgit/pyside/pyside-setup.git/
- Qt source archives: https://download.qt.io/official_releases/qt/
- Qt third-party notices: https://doc.qt.io/qt-6/licenses-used-in-qt.html
- CPython: https://github.com/python/cpython

VLC media player / libVLC is separately installed by the user and is not bundled in this release. Its sources and notices are at https://www.videolan.org/vlc/ and https://code.videolan.org/videolan/vlc.
