# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT))
build_icon = str(ROOT / 'assets/camfloat.ico')


a = Analysis(
    [str(ROOT / 'packaging/launcher.py')],
    pathex=[str(ROOT / 'src')],
    binaries=[],
    datas=[(build_icon, 'assets'), (str(ROOT / 'vendor/vlc'), 'vlc')],
    hiddenimports=['vlc'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / 'packaging/runtime_dlls.py')],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# Qt 6.12 uses the ICU API provided by Windows. A third-party Poppler ICU
# on the build machine's PATH exports incompatible, version-suffixed symbols.
# Never ship those DLLs in place of the Windows system implementation.
# Generic Qt hooks also collect unused PDF/QML/virtual-keyboard modules.
# The virtual keyboard is GPL-only; CamFloat does not use these modules.
from tools.package_release import UNUSED_QT_FILES
unused_qt_names = {path.rsplit('/', 1)[-1].lower() for path in UNUSED_QT_FILES}
a.binaries = [
    entry for entry in a.binaries
    if not (
        entry[0].replace('\\', '/').rsplit('/', 1)[-1].lower()
        in ('icu.dll', 'icuuc.dll', 'icuin.dll')
        or entry[0].replace('\\', '/').rsplit('/', 1)[-1].lower().startswith('icudt')
        or (
            entry[0].replace('\\', '/').lower().startswith('pyside6/')
            and entry[0].replace('\\', '/').rsplit('/', 1)[-1].lower() in unused_qt_names
        )
    )
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CamFloat',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[build_icon],
    version=str(ROOT / 'packaging/version_info.txt'),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CamFloat',
)
