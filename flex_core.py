"""
FLEx project access and list manipulation via flexlibs2/LCM API.

FLEx must be fully closed before calling open_project().

Startup / shutdown:
  Call flexlibs_initialize() once before opening any project.
  Call flexlibs_cleanup() once when the app exits.

Transaction safety for standalone app:
  open_project(writeEnabled=True) calls BeginNonUndoableTask() internally.
  import_items() wraps its batch in BeginUndoTask/EndUndoTask inside that,
  so a mid-import failure is rolled back while prior changes survive.

FLExTools module context:
  Use manage_undo=False in import_items() — FLExTools owns the undo task.

The FLEx LCM DLLs are located at runtime via the Windows registry key:
  HKLM\\SOFTWARE\\SIL\\FieldWorks\\9\\RootCodeDir
flexlibs2 handles this automatically; FLEx 9 must be installed on the machine.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# flexlibs2 bootstrap
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_flex_initialized = False


def ensure_flexlibs() -> bool:
    """Return True if flexlibs2 (or flextoolslib as fallback) is importable."""
    for mod in ("flexlibs2", "flextoolslib"):
        try:
            __import__(mod)
            return True
        except ImportError:
            pass
    return False


# Backward-compat alias used by flex_module.py
ensure_flextoolslib = ensure_flexlibs


def flexlibs_initialize() -> None:
    """
    Call once at app startup before opening any project.
    Initialises FWRegistryHelper, ICU, and SLDR.
    Safe to call multiple times (no-op after first call).
    """
    global _flex_initialized
    if _flex_initialized:
        return
    from flexlibs2.code.FLExInit import FLExInitialize  # type: ignore
    FLExInitialize()
    _flex_initialized = True


def flexlibs_cleanup() -> None:
    """Call once at app shutdown to clean up SLDR resources."""
    try:
        from flexlibs2.code.FLExInit import FLExCleanup  # type: ignore
        FLExCleanup()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Data model  (JSON-serialisable, no LCM dependency)
#
# Plain classes instead of @dataclass: FLExTools loads modules through a
# custom importer that leaves cls.__module__ unresolvable in sys.modules,
# which causes the dataclasses machinery to crash on Python 3.10+.
# ---------------------------------------------------------------------------

class MultiStr:
    """Multi-writing-system string: {ws_code: plain_text}."""

    def __init__(self, vals: Dict[str, str] = None):
        self.vals: Dict[str, str] = vals if vals is not None else {}

    def best(self, preferred: str = "en") -> str:
        if preferred in self.vals:
            return self.vals[preferred]
        return next(iter(self.vals.values()), "")

    def to_dict(self) -> dict:
        return dict(self.vals)

    @staticmethod
    def from_dict(d: object) -> "MultiStr":
        return MultiStr(vals=dict(d) if isinstance(d, dict) else {})


class ItemInfo:
    """Serialisable representation of one CmPossibility (or subclass) item."""

    def __init__(
        self,
        original_guid: str,
        cls: str,
        name: "MultiStr" = None,
        abbr: "MultiStr" = None,
        desc: "MultiStr" = None,
        daughters: List["ItemInfo"] = None,
    ):
        self.original_guid = original_guid
        self.cls = cls                              # e.g. "PartOfSpeech"
        self.name = name if name is not None else MultiStr()
        self.abbr = abbr if abbr is not None else MultiStr()
        self.desc = desc if desc is not None else MultiStr()
        self.daughters = daughters if daughters is not None else []

    def to_dict(self) -> dict:
        return {
            "original_guid": self.original_guid,
            "cls": self.cls,
            "name": self.name.to_dict(),
            "abbr": self.abbr.to_dict(),
            "desc": self.desc.to_dict(),
            "daughters": [d.to_dict() for d in self.daughters],
        }

    @staticmethod
    def from_dict(d: dict) -> "ItemInfo":
        return ItemInfo(
            original_guid=d.get("original_guid", ""),
            cls=d.get("cls", "CmPossibility"),
            name=MultiStr.from_dict(d.get("name", {})),
            abbr=MultiStr.from_dict(d.get("abbr", {})),
            desc=MultiStr.from_dict(d.get("desc", {})),
            daughters=[ItemInfo.from_dict(x) for x in d.get("daughters", [])],
        )


class ListInfo:
    """Metadata about one CmPossibilityList."""

    def __init__(
        self,
        guid: str,
        name: "MultiStr" = None,
        abbr: "MultiStr" = None,
        items: List[ItemInfo] = None,
    ):
        self.guid = guid
        self.name = name if name is not None else MultiStr()
        self.abbr = abbr if abbr is not None else MultiStr()
        self.items = items if items is not None else []

    @property
    def display_name(self) -> str:
        n = self.name.best()
        a = self.abbr.best()
        return f"{n} ({a})" if (n and a) else n or f"[{self.guid[:8]}]"


# ---------------------------------------------------------------------------
# LCM read helpers
# ---------------------------------------------------------------------------

def _ws_handles(project) -> Dict[str, int]:
    """Return {ws_tag: handle} for all writing systems in the project.

    project.lp is the LangProject set by FLExProject.OpenProject().
    """
    handles: Dict[str, int] = {}
    try:
        for ws in project.lp.AllWritingSystems:
            handles[ws.LanguageTag] = ws.Handle
    except Exception:
        for attr in ("DefaultAnalysisWritingSystem", "DefaultVernacularWritingSystem"):
            try:
                ws = getattr(project.lp, attr)
                handles[ws.LanguageTag] = ws.Handle
            except Exception:
                pass
    return handles


def _read_ms(lcm_ms, handles: Dict[str, int]) -> MultiStr:
    """Read an LCM MultiUnicode/MultiString into a MultiStr."""
    ms = MultiStr()
    for code, h in handles.items():
        try:
            ts = lcm_ms.get_String(h)
            text = getattr(ts, "Text", None)
            if text:
                ms.vals[code] = text
        except Exception:
            pass
    return ms


def _read_item(poss, handles: Dict[str, int]) -> ItemInfo:
    cls = type(poss).__name__.rsplit(".", 1)[-1]
    item = ItemInfo(
        original_guid=str(poss.Guid).lower(),
        cls=cls,
        name=_read_ms(poss.Name, handles),
        abbr=_read_ms(poss.Abbreviation, handles),
        desc=_read_ms(poss.Description, handles),
    )
    for sub in poss.SubPossibilitiesOS:
        item.daughters.append(_read_item(sub, handles))
    return item


def read_lists(project) -> List[ListInfo]:
    """
    Read all CmPossibilityList objects from an open FLExProject.
    Returns sorted list of ListInfo with full item hierarchy.

    project.project is the LcmCache set by FLExProject.OpenProject().
    """
    from SIL.LCModel import ICmPossibilityListRepository  # type: ignore

    cache   = project.project
    handles = _ws_handles(project)

    try:
        repo = cache.ServiceLocator.GetService(ICmPossibilityListRepository)
    except Exception as exc:
        raise RuntimeError(f"Cannot access FLEx list repository: {exc}") from exc

    results: List[ListInfo] = []
    for pl in repo.AllInstances():
        li = ListInfo(
            guid=str(pl.Guid).lower(),
            name=_read_ms(pl.Name, handles),
            abbr=_read_ms(pl.Abbreviation, handles),
        )
        for poss in pl.PossibilitiesOS:
            li.items.append(_read_item(poss, handles))
        results.append(li)

    results.sort(key=lambda li: li.name.best().lower())
    return results


# ---------------------------------------------------------------------------
# LCM write helpers
# ---------------------------------------------------------------------------

_FACTORY_FOR_CLASS: Dict[str, str] = {
    "PartOfSpeech":     "IPartOfSpeechFactory",
    "CmSemanticDomain": "ICmSemanticDomainFactory",
    "MoMorphType":      "IMoMorphTypeFactory",
    "CmAnthroItem":     "ICmAnthroItemFactory",
    "CmCustomItem":     "ICmCustomItemFactory",
    "CmLocation":       "ICmLocationFactory",
    "CmPerson":         "ICmPersonFactory",
}


def _get_factory(cache, cls_name: str):
    import SIL.LCModel as LCM  # type: ignore

    iface_name = _FACTORY_FOR_CLASS.get(cls_name, "ICmPossibilityFactory")
    iface = getattr(LCM, iface_name, None)
    if iface is None:
        iface = LCM.ICmPossibilityFactory
    try:
        return cache.ServiceLocator.GetService(iface)
    except Exception:
        return cache.ServiceLocator.GetService(LCM.ICmPossibilityFactory)


def _write_ms(lcm_ms, ms: MultiStr, handles: Dict[str, int]) -> None:
    from SIL.LCModel.Core.Text import TsStringUtils  # type: ignore

    for code, text in ms.vals.items():
        h = handles.get(code)
        if h is None:
            continue
        try:
            lcm_ms.set_String(h, TsStringUtils.MakeString(text, h))
        except Exception:
            pass


def _create_item_recursive(cache, container_os, item: ItemInfo,
                            handles: Dict[str, int]) -> None:
    factory = _get_factory(cache, item.cls)
    obj = factory.Create()
    container_os.Add(obj)
    _write_ms(obj.Name, item.name, handles)
    _write_ms(obj.Abbreviation, item.abbr, handles)
    _write_ms(obj.Description, item.desc, handles)
    for daughter in item.daughters:
        _create_item_recursive(cache, obj.SubPossibilitiesOS, daughter, handles)


# ---------------------------------------------------------------------------
# Public: import
# ---------------------------------------------------------------------------

def import_items(
    project,
    target_list_guid: str,
    items: List[ItemInfo],
    skip_duplicates: bool = True,
    manage_undo: bool = True,
) -> int:
    """
    Import items into the named list using the LCM API.

    manage_undo=True  (default) — standalone Tkinter app.
        Wraps the entire batch in project.Transaction(), which marks a
        rollback point before the first write.  If any item fails, all
        changes in the batch are rolled back automatically.
        Changes are committed to disk when CloseProject() is called.

    manage_undo=False — FLExTools module (FTM_ModifiesDB=True).
        FLExTools already manages the transaction for the whole module run.
        We just write directly; FLExTools handles commit/rollback.

    Returns the number of top-level items actually added.
    """
    import System  # type: ignore
    from SIL.LCModel import ICmPossibilityListRepository  # type: ignore

    cache   = project.project
    handles = _ws_handles(project)

    repo = cache.ServiceLocator.GetService(ICmPossibilityListRepository)
    target_guid = System.Guid(target_list_guid)
    target_list = next(
        (pl for pl in repo.AllInstances() if pl.Guid == target_guid), None
    )
    if target_list is None:
        raise ValueError(f"Target list GUID not found in project: {target_list_guid}")

    existing_names: set = set()
    if skip_duplicates:
        for poss in target_list.PossibilitiesOS:
            try:
                text = poss.Name.BestAnalysisAlternative.Text
                if text:
                    existing_names.add(text.lower())
            except Exception:
                pass

    to_import = [
        item for item in items
        if not (skip_duplicates and item.name.best().lower() in existing_names)
    ]
    if not to_import:
        return 0

    def _do_writes():
        for item in to_import:
            _create_item_recursive(cache, target_list.PossibilitiesOS, item, handles)

    if manage_undo:
        # project.Transaction() marks a rollback point; on any exception the
        # whole batch is rolled back via LCM's Mark/RollbackToMark API.
        with project.Transaction("Import FLEx list items"):
            _do_writes()
    else:
        # FLExTools module: FLExTools owns the transaction envelope.
        _do_writes()

    return len(to_import)


# ---------------------------------------------------------------------------
# Public: list matching
# ---------------------------------------------------------------------------

def find_matching_list(
    target_lists: List[ListInfo],
    source_list: ListInfo,
) -> Tuple[Optional[ListInfo], str]:
    """
    Find the best matching list in target_lists for source_list.

    Match priority:
      1. GUID — most reliable; all built-in FLEx lists share the same GUID
         across every project (Parts of Speech, Semantic Domains, etc.).
      2. Display name — fallback for custom lists or cross-version projects.

    Returns (matched_list, match_type) where match_type is one of:
      'guid'  — matched by GUID
      'name'  — matched by display name (no GUID match)
      'none'  — no match found
    """
    if source_list.guid:
        for li in target_lists:
            if li.guid == source_list.guid:
                return li, "guid"

    src_name = source_list.name.best().lower().strip()
    if src_name:
        for li in target_lists:
            if li.name.best().lower().strip() == src_name:
                return li, "name"

    return None, "none"


# ---------------------------------------------------------------------------
# Public: JSON transfer format
# ---------------------------------------------------------------------------

def save_to_json(
    items: List[ItemInfo],
    source_list: ListInfo,
    source_project_name: str,
    out_path: str | Path,
) -> None:
    data = {
        "format": "flex-list-migrator-v1",
        "source_project": source_project_name,
        "source_list_guid": source_list.guid,
        "source_list_name": source_list.name.to_dict(),
        "items": [i.to_dict() for i in items],
    }
    Path(out_path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_from_json(path: str | Path) -> Tuple[dict, List[ItemInfo]]:
    """Returns (metadata_dict, items)."""
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if data.get("format") != "flex-list-migrator-v1":
        raise ValueError(
            "This file was not exported by FLEx List Migrator.\n\n"
            "Only JSON files saved using 'Save Transfer JSON' can be loaded here."
        )
    return data, [ItemInfo.from_dict(d) for d in data.get("items", [])]


# ---------------------------------------------------------------------------
# Public: project discovery and lifecycle
# ---------------------------------------------------------------------------

def find_projects(extra_dir: Optional[str] = None) -> List[Tuple[str, str]]:
    """
    Return [(project_name, project_folder_path), ...] sorted by name.

    Uses flexlibs2's FwDirectoryFinder (registry-based) for the standard
    FLEx projects directory, so the path is always correct regardless of
    where FLEx was installed or configured.  extra_dir lets the user point
    at an additional folder (e.g. a network share).
    """
    results: List[Tuple[str, str]] = []
    seen: set = set()

    # Primary: flexlibs2 registry lookup
    try:
        from flexlibs2.code.FLExLCM import GetListOfProjects  # type: ignore
        from flexlibs2.code.FLExGlobals import FWProjectsDir  # type: ignore

        for name in GetListOfProjects():
            if name not in seen:
                seen.add(name)
                results.append((name, os.path.join(str(FWProjectsDir), name)))
    except Exception:
        pass

    # Extra directory supplied by user
    if extra_dir and os.path.isdir(extra_dir):
        from flexlibs2.code.FLExLCM import GetListOfProjects as _glop  # type: ignore
        try:
            # Temporarily override env or just scan manually
            for name in sorted(os.listdir(extra_dir)):
                if name in seen:
                    continue
                folder = os.path.join(extra_dir, name)
                if os.path.isfile(os.path.join(folder, f"{name}.fwdata")):
                    seen.add(name)
                    results.append((name, folder))
        except Exception:
            pass

    return results


def open_project(project_name: str, write_enabled: bool = True):
    """
    Open a FLEx project by name (or full .fwdata path).
    FLEx must be closed first.

    Calls flexlibs_initialize() automatically on first use.
    Returns the FLExProject instance.
    """
    flexlibs_initialize()

    from flexlibs2.code.FLExProject import FLExProject  # type: ignore

    proj = FLExProject()
    proj.OpenProject(project_name, writeEnabled=write_enabled)
    return proj


def close_project(project) -> None:
    """Save changes and release the project lock."""
    try:
        project.CloseProject()
    except Exception:
        pass
