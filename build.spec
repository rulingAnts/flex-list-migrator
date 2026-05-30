# PyInstaller build spec — FLEx List Migrator
#
# ── HOW TO BUILD (on the Windows self-hosted runner or local Windows machine) ──
#   pip install ./flexlibs2   # from the flexlibs2 repo clone
#   pip install pyinstaller
#   pyinstaller build.spec
#
# ── OUTPUT ───────────────────────────────────────────────────────────────────
#   dist\FLEx List Migrator.exe   (single portable executable)
#
# ── REQUIREMENTS ON THE TARGET MACHINE ───────────────────────────────────────
#   FieldWorks Language Explorer 9 installed.
#   FLEx must be CLOSED when the app runs.
#   No other installation needed — flexlibs2 and pythonnet are bundled.

import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# ── flexlibs2: collect all Python files from the installed package ───────────
# collect_all walks the package directory and gathers .py/.pyc files plus
# any data files.  This is file-based and does NOT trigger the module-level
# FLEx DLL loads that would fail on a machine without FLEx installed.
datas_fl, binaries_fl, hiddenimports_fl = collect_all('flexlibs2')

a = Analysis(
    ['flex_list_migrator.py'],
    pathex=[],
    binaries=binaries_fl,
    datas=datas_fl,
    hiddenimports=hiddenimports_fl + [
        'flex_core',
        'pretty_export',
        'version',
        # pythonnet
        'clr',
        'clr._extra',
        'pythonnet',
        # tkinter
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='FLEx List Migrator',      # produces "FLEx List Migrator.exe"
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app_icon.ico',
    version='version_info.txt',
)
