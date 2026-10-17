# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['vlc'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['runtime_dlls.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# Qt 6.12 uses the ICU API provided by Windows. A third-party Poppler ICU
# on the build machine's PATH exports incompatible, version-suffixed symbols.
# Never ship those DLLs in place of the Windows system implementation.
a.binaries = [
    entry for entry in a.binaries
    if not (
        entry[0].replace('\\', '/').rsplit('/', 1)[-1].lower()
        in ('icu.dll', 'icuuc.dll', 'icuin.dll')
        or entry[0].replace('\\', '/').rsplit('/', 1)[-1].lower().startswith('icudt')
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
    icon=['camfloat.ico'],
    version='version_info.txt',
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
