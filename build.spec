# PyInstaller build spec — FLEx List Migrator
#
# ── HOW TO BUILD ─────────────────────────────────────────────────────────────
#   git clone https://github.com/MattGyverLee/flexlibs.git flexlibs2_src
#   pip install ./flexlibs2_src
#   pip install pyinstaller
#   pyinstaller build.spec
#
# ── OUTPUT ───────────────────────────────────────────────────────────────────
#   dist\FLEx List Migrator.exe   (single portable executable)
#
# ── WHY NO collect_all / hiddenimports FOR flexlibs2 ─────────────────────────
# flexlibs2 loads FLEx DLLs (FwUtils, SIL.LCModel, etc.) via clr.AddReference()
# at *module import time*.  collect_all() and hiddenimports both cause PyInstaller
# to import every submodule during its analysis phase — which crashes on any
# machine without FLEx installed (including GitHub-hosted CI runners).
#
# Solution: use importlib.util.find_spec() to locate the flexlibs2 package
# directory WITHOUT importing it, then add it as a datas entry.  PyInstaller
# bundles the .py files into sys._MEIPASS; since sys._MEIPASS is on sys.path
# in the frozen app, "import flexlibs2" works normally at runtime (on the
# user's machine where FLEx IS installed and the DLL loads succeed).

import importlib.util
import os

# Locate flexlibs2 without importing it (find_spec does not execute __init__.py)
_fl2_spec = importlib.util.find_spec('flexlibs2')
if _fl2_spec is None:
    raise SystemExit(
        "flexlibs2 not found.\n"
        "Run:  pip install ./flexlibs2_src"
    )
_fl2_dir = _fl2_spec.submodule_search_locations[0]

block_cipher = None

a = Analysis(
    ['flex_list_migrator.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Bundle the entire flexlibs2 package as source files.
        # This avoids any import of flexlibs2 during PyInstaller analysis.
        (_fl2_dir, 'flexlibs2'),
    ],
    hiddenimports=[
        'flex_core',
        'pretty_export',
        'version',
        # pythonnet — safe to import/bundle without FLEx installed
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
