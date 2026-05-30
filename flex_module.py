"""
FLEx List Migrator — FLExTools Testing Module
==============================================
Use this module to test flex_core.py inside the FLExTools GUI before
packaging the standalone app.

INSTALLATION FOR TESTING
  1. Copy this file AND flex_core.py into your FLExTools Modules folder, e.g.:
       %LOCALAPPDATA%\\FLExTools\\Modules\\ListMigrator\\flex_module.py
       %LOCALAPPDATA%\\FLExTools\\Modules\\ListMigrator\\flex_core.py
  2. Open FLExTools, select a project, find "FLEx List Migrator — Test" in
     the module list, and run it.
  3. Check the Output panel for list/item counts and any errors.

WHAT THIS VALIDATES
  Read path  — ICmPossibilityListRepository.AllInstances() works,
               all writing systems are found, item hierarchy is correct.
  Write path — Creating a CmPossibility item with BeginUndoTask/EndUndoTask
               works and is undoable from FLEx (run in Modify mode).
"""

import os
import sys

# Allow flex_core to be imported when this file is in the same directory
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from flextoolslib import (  # type: ignore
    FlexToolsModuleClass,
    FTM_Description, FTM_ModifiesDB, FTM_Name, FTM_Synopsis, FTM_Version,
)

import flex_core as core


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_all(items):
    total = 0
    for item in items:
        total += 1 + _count_all(item.daughters)
    return total


def _show_item(item, report, depth=0):
    indent = "  " * depth
    name = item.name.best() or "(unnamed)"
    abbr = item.abbr.best()
    abbr_part = f" ({abbr})" if abbr else ""
    report.Info(f"{indent}  • {name}{abbr_part}")
    for d in item.daughters:
        _show_item(d, report, depth + 1)


# ---------------------------------------------------------------------------
# Cleanup helper
# ---------------------------------------------------------------------------

def _cleanup_test_items(project, report):
    """
    Delete any items whose name contains '_TEST_' and '_DELETE_ME_' from
    every CmPossibilityList in the project.  Handles top-level items only
    (daughters are owned and die with their parent).

    Must be called inside a FLExTools modify run (FLExTools manages undo).
    """
    from SIL.LCModel import ICmPossibilityListRepository  # type: ignore

    cache   = project.project
    repo    = cache.ServiceLocator.GetService(ICmPossibilityListRepository)
    deleted = 0

    for pl in repo.AllInstances():
        victims = []
        for item in pl.PossibilitiesOS:
            try:
                name = item.Name.BestAnalysisAlternative.Text or ""
                if "_TEST_" in name and "_DELETE_ME_" in name:
                    victims.append(item)
            except Exception:
                pass

        for item in victims:
            try:
                list_name = pl.Name.BestAnalysisAlternative.Text or pl.Guid.ToString()
                item_name = item.Name.BestAnalysisAlternative.Text
                pl.PossibilitiesOS.Remove(item)
                report.Info(f"  Deleted '{item_name}' from '{list_name}'")
                deleted += 1
            except Exception as exc:
                report.Warning(f"  Could not delete item: {exc}")

    if deleted == 0:
        report.Info("  No leftover test items found.")
    else:
        report.Info(f"  Cleanup complete: {deleted} item(s) removed.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def Main(project, report, modifyAllowed):

    # ── READ TEST ──────────────────────────────────────────────────────────
    report.Info("=" * 60)
    report.Info("FLEx List Migrator — READ TEST")
    report.Info("=" * 60)

    try:
        lists = core.read_lists(project)
    except Exception as exc:
        report.Error(f"read_lists() failed: {exc}")
        return

    report.Info(f"Found {len(lists)} CmPossibilityList objects.\n")

    for li in lists:
        top = len(li.items)
        total = _count_all(li.items)
        label = li.name.best() or f"[{li.guid[:8]}]"
        abbr  = li.abbr.best()
        abbr_part = f" ({abbr})" if abbr else ""
        report.Info(f"  {label}{abbr_part}  —  {top} top-level / {total} total items")

    # Show first 5 items of the first non-empty list as a sanity check
    non_empty = [li for li in lists if li.items]
    if non_empty:
        sample = non_empty[0]
        report.Info(f"\nSample items from '{sample.display_name}':")
        for item in sample.items[:5]:
            _show_item(item, report)
        if len(sample.items) > 5:
            report.Info(f"  ... and {len(sample.items) - 5} more top-level items")

    # ── WRITE TEST (modify mode only) ──────────────────────────────────────
    if not modifyAllowed:
        report.Info(
            "\nTo test the write path, run this module in Modify mode.\n"
            "IMPORTANT: Always run this module in Modify mode — running a\n"
            "FTM_ModifiesDB=True module in View mode causes a FLExTools crash."
        )
        return

    report.Info("\n" + "=" * 60)
    report.Info("FLEx List Migrator — CLEANUP: removing leftover test items")
    report.Info("=" * 60)
    _cleanup_test_items(project, report)

    report.Info("\n" + "=" * 60)
    report.Info("FLEx List Migrator — WRITE TEST (will be undoable)")
    report.Info("=" * 60)

    # Target: Text Markup Tags — visible in FLEx UI under
    # Tools > Configure > Text Markup Tags
    test_list = next(
        (li for li in lists if "text markup" in li.name.best().lower()),
        None,
    )
    if test_list is None:
        report.Warning("Could not find 'Text Markup Tags' list. Available lists:")
        for li in lists:
            report.Warning(f"  {li.display_name}")
        return

    report.Info(f"Target list: {test_list.display_name}")

    # Build a parent item with one nested child (tests 2-level hierarchy)
    dummy = core.ItemInfo(
        original_guid="test-parent",
        cls="CmPossibility",
        name=core.MultiStr(vals={"en": "_TEST_PARENT_DELETE_ME_"}),
        abbr=core.MultiStr(vals={"en": "_TP_"}),
        desc=core.MultiStr(vals={"en": "Test parent item — created by flex_module.py. Safe to delete."}),
        daughters=[
            core.ItemInfo(
                original_guid="test-child",
                cls="CmPossibility",
                name=core.MultiStr(vals={"en": "_TEST_CHILD_DELETE_ME_"}),
                abbr=core.MultiStr(vals={"en": "_TC_"}),
                desc=core.MultiStr(vals={"en": "Test child item — created by flex_module.py. Safe to delete."}),
            ),
        ],
    )

    try:
        added = core.import_items(
            project,
            target_list_guid=test_list.guid,
            items=[dummy],
            skip_duplicates=False,
            manage_undo=False,   # FLExTools manages the undo task for us
        )
        report.Info(f"Write test: {added} top-level item(s) created — PASS")
        report.Info("Open FLEx > Tools > Configure > Text Markup Tags.")
        report.Info("You should see '_TEST_PARENT_DELETE_ME_' with child '_TEST_CHILD_DELETE_ME_'.")
        report.Info("Run this module again in Modify mode to clean them up.")
    except Exception as exc:
        report.Error(f"Write test FAILED: {exc}")


# ---------------------------------------------------------------------------
# FLExTools module registration
# ---------------------------------------------------------------------------

docs = {
    FTM_Name:        "FLEx List Migrator — Test",
    FTM_Version:     1,
    FTM_ModifiesDB:  True,
    FTM_Synopsis:    "Validates flex_core read/write before standalone packaging.",
    FTM_Description: __doc__,
}

FlexToolsModule = FlexToolsModuleClass(runFunction=Main, docs=docs)

if __name__ == "__main__":
    print(FlexToolsModule.Help())
