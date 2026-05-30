"""
Patch flexlibs2 source for headless CI builds (no FLEx installed).

Applied once, to the cloned flexlibs2 repo, before 'pip install ./flexlibs2_src'.

Three files have module-level code that reads the Windows registry and loads
FLEx DLLs at import time.  On a CI runner without FLEx installed every import
of a flexlibs2 submodule fails, crashing PyInstaller's analysis phase.

These patches wrap that code so import succeeds gracefully when FLEx is absent.
The changes are *backward-compatible*: on a machine WITH FLEx the same code
paths run as before (the exception handlers are never triggered).

Usage:
    python ci_patch_flexlibs2.py flexlibs2_src
"""

import sys
from pathlib import Path

if len(sys.argv) != 2:
    print(f"Usage: python {sys.argv[0]} <flexlibs2_repo_dir>")
    sys.exit(1)

root = Path(sys.argv[1]) / "flexlibs2" / "code"
if not root.is_dir():
    print(f"ERROR: {root} not found — check the repo path")
    sys.exit(1)

ok = True


def patch(path: Path, old: str, new: str, label: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        print(f"  SKIP  {label}  (pattern not found — version may differ)")
        return False
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"  OK    {label}")
    return True


print("Patching flexlibs2 for headless build...")

# ── 1. FLExGlobals.py ────────────────────────────────────────────────────────
# InitialiseFWGlobals() re-raises when FLEx registry key is missing.
# Change the re-raise to a silent return so import succeeds without FLEx.
ok &= patch(
    root / "FLExGlobals.py",
    old=(
        '        logging.exception("Couldn\'t find FieldWorks registry entry")\n'
        '        raise\n'
    ),
    new=(
        '        logging.warning("FLEx not installed (headless/CI build context)")\n'
        '        return\n'
    ),
    label="FLExGlobals.py — make registry-not-found non-fatal",
)

# ── 2. FLExInit.py ───────────────────────────────────────────────────────────
# Module-level code calls InitialiseFWGlobals() then immediately loads FLEx
# DLLs via clr.AddReference.  Wrap the whole block in try/except.
ok &= patch(
    root / "FLExInit.py",
    old=(
        'FLExGlobals.InitialiseFWGlobals()\n'
        '\n'
        'clr.AddReference("FwUtils")\n'
        'from SIL.FieldWorks.Common.FwUtils import FwRegistryHelper, FwUtils\n'
        '\n'
        'clr.AddReference("SIL.WritingSystems")\n'
        'from SIL.WritingSystems import Sldr\n'
    ),
    new=(
        '# Wrapped for headless/CI builds: non-fatal when FLEx is not installed.\n'
        '# On machines WITH FLEx these succeed normally; stubs are never used.\n'
        'try:\n'
        '    FLExGlobals.InitialiseFWGlobals()\n'
        '    clr.AddReference("FwUtils")\n'
        '    from SIL.FieldWorks.Common.FwUtils import FwRegistryHelper, FwUtils\n'
        '    clr.AddReference("SIL.WritingSystems")\n'
        '    from SIL.WritingSystems import Sldr\n'
        'except Exception:\n'
        '    FwRegistryHelper = None\n'
        '    FwUtils = None\n'
        '    Sldr = None\n'
    ),
    label="FLExInit.py  — wrap module-level FLEx DLL loads",
)

# ── 3. FLExLCM.py ────────────────────────────────────────────────────────────
# Module-level code loads ~9 FLEx-specific assemblies and imports many
# SIL.LCModel / SIL.FieldWorks types.  clr.AddReference("System") is left
# outside the try/except because System is standard .NET (always available).
ok &= patch(
    root / "FLExLCM.py",
    old=(
        'clr.AddReference("FwUtils")\n'
        'clr.AddReference("FieldWorks")\n'
        'clr.AddReference("FwCoreDlgs")\n'
        'clr.AddReference("FwControls")\n'
        'clr.AddReference("FdoUi")\n'
        'clr.AddReference("SIL.Core")\n'
        'clr.AddReference("SIL.Core.Desktop")\n'
        'clr.AddReference("SIL.LCModel")\n'
        'clr.AddReference("SIL.LCModel.Core")\n'
        '\n'
        '# Classes needed for loading the Cache\n'
        'from SIL.LCModel import LcmCache, LcmSettings, LcmFileHelper\n'
        'from SIL.LCModel.Core.Cellar import CellarPropertyType as _LCMCellarPropertyType\n'
        '\n'
        'from SIL.FieldWorks import ProjectId\n'
        'from SIL.FieldWorks.Common.Controls import ProgressDialogWithTask\n'
        'from SIL.FieldWorks.Common.FwUtils import ThreadHelper\n'
        'from SIL.FieldWorks.Common.FwUtils import FwDirectoryFinder\n'
        'from SIL.FieldWorks.Common.FwUtils import FwUtils\n'
        'from SIL.FieldWorks.FdoUi import FwLcmUI\n'
        'from SIL.FieldWorks.FwCoreDlgs import ChooseLangProjectDialog\n'
        '\n'
        '# Import Python mirror of CellarPropertyType constants\n'
        'from .Shared.lcm_constants import CellarPropertyType\n'
    ),
    new=(
        '# Wrapped for headless/CI builds: non-fatal when FLEx is not installed.\n'
        'try:\n'
        '    clr.AddReference("FwUtils")\n'
        '    clr.AddReference("FieldWorks")\n'
        '    clr.AddReference("FwCoreDlgs")\n'
        '    clr.AddReference("FwControls")\n'
        '    clr.AddReference("FdoUi")\n'
        '    clr.AddReference("SIL.Core")\n'
        '    clr.AddReference("SIL.Core.Desktop")\n'
        '    clr.AddReference("SIL.LCModel")\n'
        '    clr.AddReference("SIL.LCModel.Core")\n'
        '    from SIL.LCModel import LcmCache, LcmSettings, LcmFileHelper\n'
        '    from SIL.LCModel.Core.Cellar import CellarPropertyType as _LCMCellarPropertyType\n'
        '    from SIL.FieldWorks import ProjectId\n'
        '    from SIL.FieldWorks.Common.Controls import ProgressDialogWithTask\n'
        '    from SIL.FieldWorks.Common.FwUtils import ThreadHelper\n'
        '    from SIL.FieldWorks.Common.FwUtils import FwDirectoryFinder\n'
        '    from SIL.FieldWorks.Common.FwUtils import FwUtils\n'
        '    from SIL.FieldWorks.FdoUi import FwLcmUI\n'
        '    from SIL.FieldWorks.FwCoreDlgs import ChooseLangProjectDialog\n'
        'except Exception:\n'
        '    LcmCache = LcmSettings = LcmFileHelper = None\n'
        '    _LCMCellarPropertyType = None\n'
        '    ProjectId = ProgressDialogWithTask = None\n'
        '    ThreadHelper = FwDirectoryFinder = FwUtils = None\n'
        '    FwLcmUI = ChooseLangProjectDialog = None\n'
        '\n'
        '# Import Python mirror of CellarPropertyType constants\n'
        'from .Shared.lcm_constants import CellarPropertyType\n'
    ),
    label="FLExLCM.py   — wrap module-level FLEx DLL loads",
)

if not ok:
    print("\nOne or more patches were skipped. The build may still work if")
    print("flexlibs2 was already patched or the patterns changed in a newer version.")
else:
    print("\nAll patches applied. Run: pip install ./flexlibs2_src")
