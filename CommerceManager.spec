# -*- mode: python ; coding: utf-8 -*-
# Build with:  pyinstaller CommerceManager.spec
# Output:      dist/CommerceManager.exe

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('views', 'views')],
    hiddenimports=[
        'webview.platforms.winforms',
        'webview.platforms.edgechromium',
        'win32crypt',       # DPAPI, used by license/storage.py - pywin32 modules
        'win32timezone',    # often needed alongside pywin32 in PyInstaller builds
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='CommerceManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # no black console window - real app behavior
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Drop your own icon at assets/icon.ico and uncomment the line below
    # icon='assets/icon.ico',
)
