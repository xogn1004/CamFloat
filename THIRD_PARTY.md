# Third-party components

CamFloat uses the following unmodified runtime components. License texts are in `licenses/`.

| Component | Version | Project / license |
| --- | --- | --- |
| CPython | 3.14.4 | https://www.python.org/ · Python license, including bundled third-party notices |
| PySide6 / Shiboken6 / Qt | 6.12.0 | https://www.qt.io/qt-for-python · LGPL-3.0 / GPL alternatives described in package metadata |
| python-vlc | 3.0.21203 | https://github.com/oaubert/python-vlc · LGPL-2.1-or-later |
| libVLC | 3.0.23 (x64) | Official VideoLAN.LibVLC.Windows LGPL package; see `licenses/VLC-SOURCES.txt` |
| PyInstaller bootloader | 6.22.3 | https://pyinstaller.org/ · GPL with the bootloader distribution exception |
| cryptography | 46.0.3 | https://cryptography.io/ · Apache-2.0 or BSD-3-Clause; bundled wheel uses OpenSSL |
| OpenSSL (via cryptography) | 3.5.4 | https://www.openssl.org/ · Apache-2.0 |
| cffi | 2.1.1 | https://cffi.readthedocs.io/ · MIT |
| pycparser | 3.11 | https://github.com/eliben/pycparser · BSD-3-Clause |

Qt and Python runtime DLLs are distributed as separate files in `_internal/`; replacement of these libraries is not restricted by CamFloat. Corresponding upstream sources and notices:

- Qt for Python: https://code.qt.io/cgit/pyside/pyside-setup.git/
- Qt source archives: https://download.qt.io/official_releases/qt/
- Qt third-party notices: https://doc.qt.io/qt-6/licenses-used-in-qt.html
- CPython: https://github.com/python/cpython

libVLC DLLs and the official LGPL package's plugins are bundled unmodified in `_internal/vlc`. VLC desktop player and the GPL plugin add-on are not bundled. The engine DLLs and plugins remain replaceable. Source/package references, version and package checksum are in `licenses/VLC-SOURCES.txt`; the LGPL-2.1 text is `licenses/python-vlc-COPYING.txt`.
