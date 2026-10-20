# Third-party components

CamFloat uses the following unmodified runtime components. License texts are in `licenses/`.

CamFloat's own source is under the MIT license (`LICENSE`). This does not change
the licenses of the third-party components below. `licenses/CamFloat-MIT.txt`
in the application ZIP is a copy of the root MIT license.

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

## Release sources and notices

The [1.1.1 release](https://github.com/xogn1004/CamFloat/releases/tag/v1.1.1)
also provides the unmodified Qt Base, Qt Image Formats, Qt SVG, PySide6/Shiboken6,
libVLC and python-vlc source archives. They are separate developer downloads;
they are not required to run CamFloat. Archive URLs, versions, byte sizes and
SHA-256 hashes are recorded in [the source manifest](docs/third-party-sources.json).
All six source archives were checked against upstream checksums.

Qt PDF, Qt QML/Quick, Qt Virtual Keyboard and the software OpenGL fallback are
not used and are excluded from the application ZIP. In particular, the GPL-only
Qt Virtual Keyboard plugin is not part of the MIT application distribution.

`licenses/UPSTREAM-COPYRIGHTS.txt` preserves the license/copyright texts from
the included libraries' source archives, including their third-party notices.
VLC's source archive includes its dependency build recipes and patches; further
third-party source locations and the VideoLAN source mirror are listed in
`licenses/VLC-SOURCES.txt`.

## Building or replacing libraries

CamFloat's complete application source and [build instructions](docs/development.md)
are provided in this repository. Qt/PySide/Shiboken and libVLC are dynamically
loaded as separate files in `_internal`. You may replace them with compatible
user-modified builds, including for debugging such modifications. Keep x64
libraries and their matching plugins together. CamFloat imposes no restriction
on reverse engineering for debugging changes to these LGPL libraries.

For the bundled LGPL libraries, obtain the matching source archives from the
same release assets or the official URLs in the source manifest. Preserve the
upstream license notices and follow each upstream project's build instructions.
No modifications were made to these libraries.
