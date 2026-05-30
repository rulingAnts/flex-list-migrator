# PyInstaller build spec — FLEx List Migrator
#
# ── PRE-BUILD CHECKLIST (run on Windows) ──────────────────────────────────
#   1. pip install flexlibs2 pyinstaller
#   2. pyinstaller build.spec
#   3. Output: dist\FLExListMigrator.exe
#
# ── WHAT THE .exe BUNDLES ─────────────────────────────────────────────────
#   • Our Python source (flex_list_migrator.py, flex_core.py, pretty_export.py)
#   • flexlibs2 and all its dependencies (pythonnet / clr, etc.)
#   • Python stdlib including tkinter
#
# ── WHAT MUST BE ON THE TARGET MACHINE ───────────────────────────────────
#   • FieldWorks Language Explorer 9
#     flexlibs2 locates FLEx's LCM DLLs via the registry / standard install
#     paths at runtime — no manual path configuration needed.
#   • FLEx must be CLOSED when the app runs.

block_cipher = None

a = Analysis(
    ["flex_list_migrator.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        "flex_core",
        "pretty_export",
        # flexlibs2 and its internals
        "flexlibs2",
        "flextoolslib",
        # pythonnet
        "clr",
        "clr._extra",
        "pythonnet",
        # tkinter
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
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
    name="FLExListMigrator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                # no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                    # set to "icon.ico" if you have one
)
