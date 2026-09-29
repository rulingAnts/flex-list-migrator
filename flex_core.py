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

import copy
import json
import os
import sys
import uuid
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


# Rich text (an LCM TsString) is carried as a list of runs:
#   [{"text": "...", "ws": "en", "style": "Emphasized Text"}, ...]
# "ws" and "style" are optional.  A paragraph of a Discussion is one such
# list.  A reference to an item in another list (Status, Confidence Levels,
# People, Restrictions) is {"guid": "...", "name": {ws_code: text}}; on
# import it is resolved by GUID first, then by name.

def _norm_runs(value: object) -> List[dict]:
    """Coerce a JSON run list (or a bare string) into [{"text", "ws"?, "style"?}]."""
    if isinstance(value, str):
        value = [{"text": value}]
    runs: List[dict] = []
    for r in value if isinstance(value, list) else []:
        if isinstance(r, str):
            r = {"text": r}
        if not isinstance(r, dict) or not isinstance(r.get("text"), str) or not r["text"]:
            continue
        run = {"text": r["text"]}
        for key in ("ws", "style"):
            if isinstance(r.get(key), str) and r[key]:
                run[key] = r[key]
        runs.append(run)
    return runs


def _norm_ref(value: object) -> Optional[dict]:
    """Coerce a JSON list-item reference into {"guid", "name"}; None if empty."""
    if isinstance(value, str):
        value = {"name": {"en": value}}
    if not isinstance(value, dict):
        return None
    guid = str(value.get("guid") or "").lower()
    name = MultiStr.from_dict(value.get("name", {})).to_dict()
    return {"guid": guid, "name": name} if (guid or name) else None


def runs_text(runs: List[dict]) -> str:
    """Plain text of a run list."""
    return "".join(r.get("text", "") for r in runs)


def ref_label(ref: Optional[dict], preferred: str = "en") -> str:
    """Display name of a list-item reference."""
    if not ref:
        return ""
    return MultiStr(ref.get("name", {})).best(preferred) or f"[{ref.get('guid', '')[:8]}]"


class ItemInfo:
    """Serialisable representation of one CmPossibility (or subclass) item.

    Carries every field FLEx shows for a generic list item: Name, Abbreviation,
    Description, Discussion, Status, Confidence, Researchers, Restrictions and
    the subitems.  Not carried: SortSpec, HelpId, the overlay colours and
    Hidden flag, IsProtected and the created/modified dates — LCM manages
    these itself and FLEx does not show them for list items.  Fields that only
    a subclass has (e.g. a Part of Speech's inflection features) are not
    carried either.
    """

    def __init__(
        self,
        original_guid: str,
        cls: str,
        name: "MultiStr" = None,
        abbr: "MultiStr" = None,
        desc: "MultiStr" = None,
        daughters: List["ItemInfo"] = None,
        desc_runs: Dict[str, List[dict]] = None,
        discussion: List[List[dict]] = None,
        status: Optional[dict] = None,
        confidence: Optional[dict] = None,
        researchers: List[dict] = None,
        restrictions: List[dict] = None,
    ):
        self.original_guid = original_guid
        self.cls = cls                              # e.g. "PartOfSpeech"
        self.name = name if name is not None else MultiStr()
        self.abbr = abbr if abbr is not None else MultiStr()
        self.desc = desc if desc is not None else MultiStr()
        self.daughters = daughters if daughters is not None else []
        # Description alternatives that carry formatting (embedded writing
        # systems or character styles): {ws_code: runs}.  desc keeps the
        # plain text of every alternative either way.
        self.desc_runs = desc_runs if desc_runs is not None else {}
        self.discussion = discussion if discussion is not None else []  # paragraphs
        self.status = status
        self.confidence = confidence
        self.researchers = researchers if researchers is not None else []
        self.restrictions = restrictions if restrictions is not None else []

    def copy(self, daughters: List["ItemInfo"] = None) -> "ItemInfo":
        """Shallow copy, optionally with a different daughters list."""
        dup = copy.copy(self)
        dup.daughters = list(self.daughters) if daughters is None else daughters
        return dup

    def to_dict(self) -> dict:
        d = {
            "original_guid": self.original_guid,
            "cls": self.cls,
            "name": self.name.to_dict(),
            "abbr": self.abbr.to_dict(),
            "desc": self.desc.to_dict(),
        }
        # Optional fields are written only when present, so older versions of
        # this tool can still read the file (they ignore keys they don't know).
        if self.desc_runs:
            d["desc_runs"] = self.desc_runs
        if self.discussion:
            d["discussion"] = self.discussion
        for key in ("status", "confidence"):
            if getattr(self, key):
                d[key] = getattr(self, key)
        for key in ("researchers", "restrictions"):
            if getattr(self, key):
                d[key] = getattr(self, key)
        d["daughters"] = [x.to_dict() for x in self.daughters]
        return d

    @staticmethod
    def from_dict(d: dict) -> "ItemInfo":
        desc = MultiStr.from_dict(d.get("desc", {}))
        desc_runs: Dict[str, List[dict]] = {}
        raw_runs = d.get("desc_runs")
        for code, runs in (raw_runs.items() if isinstance(raw_runs, dict) else []):
            runs = _norm_runs(runs)
            if runs:
                desc_runs[code] = runs
                desc.vals.setdefault(code, runs_text(runs))
        raw_disc = d.get("discussion")
        return ItemInfo(
            original_guid=d.get("original_guid", ""),
            cls=d.get("cls", "CmPossibility"),
            name=MultiStr.from_dict(d.get("name", {})),
            abbr=MultiStr.from_dict(d.get("abbr", {})),
            desc=desc,
            daughters=[ItemInfo.from_dict(x) for x in d.get("daughters", [])],
            desc_runs=desc_runs,
            discussion=[_norm_runs(p) for p in (raw_disc if isinstance(raw_disc, list) else [])],
            status=_norm_ref(d.get("status")),
            confidence=_norm_ref(d.get("confidence")),
            researchers=[r for r in map(_norm_ref, d.get("researchers") or []) if r],
            restrictions=[r for r in map(_norm_ref, d.get("restrictions") or []) if r],
        )


# Labels for built-in lists whose Name may be empty in a project, keyed by the
# field that owns the list (see ListInfo.owner).
_OWNER_LABELS: Dict[str, str] = {
    "DsDiscourseData.ChartMarkers":   "Text Chart Markers",
    "DsDiscourseData.ConstChartTempl": "Text Constituent Chart Templates",
}


class ListInfo:
    """Metadata about one CmPossibilityList."""

    def __init__(
        self,
        guid: str,
        name: "MultiStr" = None,
        abbr: "MultiStr" = None,
        items: List[ItemInfo] = None,
        owner: str = "",
    ):
        self.guid = guid
        self.name = name if name is not None else MultiStr()
        self.abbr = abbr if abbr is not None else MultiStr()
        self.items = items if items is not None else []
        # Owning class and field, e.g. "DsDiscourseData.ChartMarkers".  Built-in
        # lists have exactly one owner field, so this identifies the same list
        # across projects even when its GUID differs.  Empty for custom lists.
        self.owner = owner

    @property
    def display_name(self) -> str:
        n = self.name.best() or _OWNER_LABELS.get(self.owner, "")
        a = self.abbr.best()
        return f"{n} ({a})" if (n and a) else n or self.owner or f"[{self.guid[:8]}]"


# ---------------------------------------------------------------------------
# Supported lists
#
# This release exports and imports only the lists below.  Their items are all
# plain CmPossibility objects, which the importer handles completely.  Other
# lists can be browsed but not exported or imported yet: some hold kinds of
# item the importer can't create (LexEntryType, LexRefType, CmAnnotationDefn,
# ...) and some have fields specific to their items that aren't carried (e.g. a
# Part of Speech's inflection features).  See "Known issues" in README.md.
# ---------------------------------------------------------------------------

SUPPORTED_LISTS: Dict[str, str] = {     # owning field -> list name
    "DsDiscourseData.ChartMarkers":    "Text Chart Markers",
    "LangProject.TextMarkupTags":      "Text Markup Tags",
    "DsDiscourseData.ConstChartTempl": "Text Constituent Chart Templates",
}
SUPPORTED_ITEM_CLASSES = {"CmPossibility"}

NOT_SUPPORTED_YET = (
    "This version of FLEx List Migrator can export and import only "
    + ", ".join(list(SUPPORTED_LISTS.values())[:-1]) + " and "
    + list(SUPPORTED_LISTS.values())[-1] + ". Support for other lists may come "
    "in a future release."
)


def is_supported_list(li: ListInfo) -> bool:
    """True for the lists this release can export and import."""
    if li.owner:
        return li.owner in SUPPORTED_LISTS
    # Transfer files from 1.0.x don't record the owning field; go by name.
    return li.name.best().strip().lower() in {n.lower() for n in SUPPORTED_LISTS.values()}


def unsupported_classes(items: List[ItemInfo]) -> List[str]:
    """Item classes among items (and their subitems) that can't be imported yet."""
    found: set = set()

    def walk(xs: List[ItemInfo]) -> None:
        for it in xs:
            if norm_cls(it.cls) not in SUPPORTED_ITEM_CLASSES:
                found.add(it.cls)
            walk(it.daughters)

    walk(items)
    return sorted(found)


def unsupported_reason(li: ListInfo, items: Optional[List[ItemInfo]] = None) -> Optional[str]:
    """Why this list (or these items) can't be exported or imported yet; None if they can."""
    if not is_supported_list(li):
        return f"“{li.display_name}” is not supported yet. {NOT_SUPPORTED_YET}"
    bad = unsupported_classes(li.items if items is None else items)
    if bad:
        return ("This list contains kinds of list item that can't be imported yet ("
                + ", ".join(bad) + f"). {NOT_SUPPORTED_YET}")
    return None


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


_text_props: Optional[Tuple[int, int, Optional[int]]] = None


def _text_prop_consts() -> Tuple[int, int, Optional[int]]:
    """(ktptWs, ktpvDefault, ktptNamedStyle) from the LCM enums.

    If the enums can't be loaded, fall back to the fixed ktptWs/ktpvDefault
    values and leave character styles out (None) rather than guess a number.
    """
    global _text_props
    if _text_props is None:
        try:
            from SIL.LCModel.Core.KernelInterfaces import (  # type: ignore
                FwTextPropType, FwTextPropVar,
            )
            _text_props = (int(FwTextPropType.ktptWs), int(FwTextPropVar.ktpvDefault),
                           int(FwTextPropType.ktptNamedStyle))
        except Exception:
            _text_props = (1, 0, None)
    return _text_props


def _read_runs(tss, ws_codes: Dict[int, str]) -> List[dict]:
    """Split an LCM ITsString into runs, keeping each run's WS and character style."""
    ktpt_ws, _, ktpt_style = _text_prop_consts()
    runs: List[dict] = []
    try:
        count = tss.RunCount
    except Exception:
        text = getattr(tss, "Text", None)
        return [{"text": text}] if text else []
    for i in range(count):
        text = tss.get_RunText(i)
        if not text:
            continue
        run = {"text": text}
        try:
            props = tss.get_Properties(i)
            code = ws_codes.get(props.GetIntPropValues(ktpt_ws, 0)[0])
            if code:
                run["ws"] = code
            if ktpt_style is not None:
                style = props.GetStrPropValue(ktpt_style)
                if style:
                    run["style"] = style
        except Exception:
            pass
        runs.append(run)
    return runs


def _read_desc(lcm_ms, handles: Dict[str, int],
               ws_codes: Dict[int, str]) -> Tuple[MultiStr, Dict[str, List[dict]]]:
    """Read a MultiString as plain text, plus runs for alternatives with formatting."""
    ms = MultiStr()
    rich: Dict[str, List[dict]] = {}
    for code, h in handles.items():
        try:
            ts = lcm_ms.get_String(h)
            text = getattr(ts, "Text", None)
        except Exception:
            continue
        if not text:
            continue
        ms.vals[code] = text
        runs = _read_runs(ts, ws_codes)
        if len(runs) > 1 or any(r.get("style") or r.get("ws", code) != code for r in runs):
            rich[code] = runs
    return ms, rich


def _read_discussion(poss, ws_codes: Dict[int, str]) -> List[List[dict]]:
    """Read the Discussion (an StText) as a list of paragraphs of runs."""
    from SIL.LCModel import IStTxtPara  # type: ignore

    sttext = poss.DiscussionOA
    if sttext is None:
        return []
    paras: List[List[dict]] = []
    for para in sttext.ParagraphsOS:
        try:
            contents = IStTxtPara(para).Contents
        except Exception:
            continue
        paras.append(_read_runs(contents, ws_codes) if contents is not None else [])
    while paras and not paras[-1]:
        paras.pop()
    return paras


def _read_ref(poss, handles: Dict[str, int]) -> Optional[dict]:
    """Reference to an item of another list: its GUID and name."""
    if poss is None:
        return None
    return {"guid": str(poss.Guid).lower(), "name": _read_ms(poss.Name, handles).to_dict()}


def _class_name(poss) -> str:
    """LCM class of an item, e.g. "PartOfSpeech".

    ClassName is the object's real class; the Python type name may only be
    the interface it was returned as (e.g. "ICmPossibility").
    """
    try:
        name = poss.ClassName
        if name:
            return str(name)
    except Exception:
        pass
    return norm_cls(type(poss).__name__.rsplit(".", 1)[-1])


def _read_item(poss, handles: Dict[str, int], ws_codes: Dict[int, str]) -> ItemInfo:
    desc, desc_runs = _read_desc(poss.Description, handles, ws_codes)
    item = ItemInfo(
        original_guid=str(poss.Guid).lower(),
        cls=_class_name(poss),
        name=_read_ms(poss.Name, handles),
        abbr=_read_ms(poss.Abbreviation, handles),
        desc=desc,
        desc_runs=desc_runs,
        discussion=_read_discussion(poss, ws_codes),
        status=_read_ref(poss.StatusRA, handles),
        confidence=_read_ref(poss.ConfidenceRA, handles),
        researchers=[_read_ref(p, handles) for p in poss.ResearchersRC],
        restrictions=[_read_ref(p, handles) for p in poss.RestrictionsRC],
    )
    for sub in poss.SubPossibilitiesOS:
        item.daughters.append(_read_item(sub, handles, ws_codes))
    return item


def _owner_field(cache, pl) -> str:
    """"Class.Field" that owns the list, e.g. "DsDiscourseData.ChartMarkers"."""
    try:
        owner = pl.Owner
        if owner is None:
            return ""
        field = cache.MetaDataCacheAccessor.GetFieldName(pl.OwningFlid)
        return f"{owner.ClassName}.{field}"
    except Exception:
        return ""


def read_lists(project) -> List[ListInfo]:
    """
    Read all CmPossibilityList objects from an open FLExProject.
    Returns sorted list of ListInfo with full item hierarchy.

    project.project is the LcmCache set by FLExProject.OpenProject().
    """
    from SIL.LCModel import ICmPossibilityListRepository  # type: ignore

    cache    = project.project
    handles  = _ws_handles(project)
    ws_codes = {h: code for code, h in handles.items()}

    try:
        repo = cache.ServiceLocator.GetService(ICmPossibilityListRepository)
    except Exception as exc:
        raise RuntimeError(f"Cannot access FLEx list repository: {exc}") from exc

    results: List[ListInfo] = []
    for pl in repo.AllInstances():
        li = _list_info(cache, pl, handles)
        for poss in pl.PossibilitiesOS:
            li.items.append(_read_item(poss, handles, ws_codes))
        results.append(li)

    results.sort(key=lambda li: li.display_name.lower())
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


def norm_cls(cls_name: str) -> str:
    """Class name without an interface "I" prefix ("ICmPossibility" -> "CmPossibility").

    Older exports may carry the interface name pythonnet reported.
    """
    if cls_name[:1] == "I" and cls_name[1:2].isupper():
        return cls_name[1:]
    return cls_name


def _get_factory(cache, cls_name: str):
    import SIL.LCModel as LCM  # type: ignore

    iface_name = _FACTORY_FOR_CLASS.get(norm_cls(cls_name), "ICmPossibilityFactory")
    iface = getattr(LCM, iface_name, None)
    if iface is None:
        iface = LCM.ICmPossibilityFactory
    try:
        return cache.ServiceLocator.GetService(iface)
    except Exception:
        return cache.ServiceLocator.GetService(LCM.ICmPossibilityFactory)


class _ItemWriter:
    """Creates list items in a target project.

    Anything that can't be carried over as-is (a writing system or character
    style the target lacks, a referenced Status/Confidence/People/Restrictions
    item it doesn't have) is left out or simplified and noted in ``warnings``
    rather than failing the whole import.  With preview=True, check() finds
    the same things without writing, worded as what *will* happen.
    """

    # ItemInfo field -> (LangProject property holding the list, label)
    _REF_LISTS = {
        "status":       ("StatusOA",           "Status"),
        "confidence":   ("ConfidenceLevelsOA", "Confidence Levels"),
        "researchers":  ("PeopleOA",           "People"),
        "restrictions": ("RestrictionsOA",     "Restrictions"),
    }

    def __init__(self, project, handles: Dict[str, int], warnings: List[str],
                 preview: bool = False):
        self.cache = project.project
        self.lp = project.lp
        self.handles = handles
        self.warnings = warnings
        self.preview = preview
        self.default_ws = self.cache.DefaultAnalWs
        self._styles: Optional[set] = None
        self._styles_loaded = False
        self._ref_index: Dict[str, Tuple[dict, dict]] = {}

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    def _did(self, past: str, future: str) -> str:
        return future if self.preview else past

    def _note_missing_ws(self, code: str) -> None:
        self.warn(f"Writing system '{code}' is not in the target project, so text in it "
                  + self._did("was not imported.", "will not be imported."))

    def check(self, item: ItemInfo) -> None:
        """Preview: note what create() would have to leave out, without writing."""
        label = item.name.best() or "(unnamed)"
        for ms in (item.name, item.abbr, item.desc):
            for code in ms.vals:
                if code not in self.handles:
                    self._note_missing_ws(code)
        runs = [r for rs in list(item.desc_runs.values()) + item.discussion for r in rs]
        if _text_prop_consts()[2] is None and any(r.get("style") for r in runs):
            self._note_no_styles()
        for run in runs:
            self._run_ws(run, self.default_ws)
            self._run_style(run)
        for field in ("status", "confidence"):
            if getattr(item, field):
                self._find_ref(field, getattr(item, field), label)
        for field in ("researchers", "restrictions"):
            for ref in getattr(item, field):
                self._find_ref(field, ref, label)
        for daughter in item.daughters:
            self.check(daughter)

    def create(self, container_os, item: ItemInfo) -> None:
        factory = _get_factory(self.cache, item.cls)
        obj = factory.Create()
        container_os.Add(obj)
        label = item.name.best() or "(unnamed)"
        self._write_ms(obj.Name, item.name, label)
        self._write_ms(obj.Abbreviation, item.abbr, label)
        self._write_desc(obj, item, label)
        self._write_discussion(obj, item.discussion, label)
        self._write_refs(obj, item, label)
        for daughter in item.daughters:
            self.create(obj.SubPossibilitiesOS, daughter)

    # -- strings --------------------------------------------------------------

    def _write_ms(self, lcm_ms, ms: MultiStr, label: str) -> None:
        from SIL.LCModel.Core.Text import TsStringUtils  # type: ignore

        for code, text in ms.vals.items():
            h = self.handles.get(code)
            if h is None:
                self._note_missing_ws(code)
                continue
            try:
                lcm_ms.set_String(h, TsStringUtils.MakeString(text, h))
            except Exception as exc:
                self.warn(f"'{label}': text in '{code}' could not be written ({exc}).")

    def _write_desc(self, obj, item: ItemInfo, label: str) -> None:
        from SIL.LCModel.Core.Text import TsStringUtils  # type: ignore

        for code, text in item.desc.vals.items():
            h = self.handles.get(code)
            if h is None:
                self._note_missing_ws(code)
                continue
            runs = item.desc_runs.get(code)
            tss = self._make_tss(runs, label, h) if runs else None
            obj.Description.set_String(h, tss or TsStringUtils.MakeString(text, h))

    def _write_discussion(self, obj, paragraphs: List[List[dict]], label: str) -> None:
        paras = [runs for runs in paragraphs if runs_text(runs)]
        if not paras:
            return
        from SIL.LCModel import IStTextFactory, IStTxtParaFactory  # type: ignore

        sttext = self.cache.ServiceLocator.GetService(IStTextFactory).Create()
        obj.DiscussionOA = sttext
        para_factory = self.cache.ServiceLocator.GetService(IStTxtParaFactory)
        for runs in paras:
            para = para_factory.Create()
            sttext.ParagraphsOS.Add(para)       # own it before setting Contents
            para.Contents = self._make_tss(runs, label, self.default_ws)

    def _make_tss(self, runs: List[dict], label: str, base_ws: int):
        """Build an ITsString from runs; a run without "ws" uses base_ws."""
        from SIL.LCModel.Core.Text import TsStringUtils  # type: ignore

        runs = [r for r in runs if r.get("text")]
        if not runs:
            return None
        if len(runs) == 1 and not runs[0].get("style"):
            return TsStringUtils.MakeString(runs[0]["text"], self._run_ws(runs[0], base_ws))
        ktpt_ws, ktpv_default, ktpt_style = _text_prop_consts()
        if ktpt_style is None and any(r.get("style") for r in runs):
            self._note_no_styles()
        try:
            bldr = TsStringUtils.MakeIncStrBldr()
            for r in runs:
                bldr.SetIntPropValues(ktpt_ws, ktpv_default, self._run_ws(r, base_ws))
                if ktpt_style is not None:
                    bldr.SetStrPropValue(ktpt_style, self._run_style(r))
                bldr.Append(r["text"])
            return bldr.GetString()
        except Exception as exc:
            self.warn(f"'{label}': formatting could not be applied ({exc}), "
                      "so the text was imported without it.")
            return TsStringUtils.MakeString(runs_text(runs), self._run_ws(runs[0], base_ws))

    def _note_no_styles(self) -> None:
        self.warn("Character styles can't be applied with this FLEx version, so styled "
                  "text " + self._did("was imported unstyled.", "will be imported unstyled."))

    def _run_ws(self, run: dict, base_ws: int) -> int:
        code = run.get("ws")
        if not code:
            return base_ws
        h = self.handles.get(code)
        if h is None:
            self.warn(f"Writing system '{code}' is not in the target project, so formatted "
                      "text in it " + self._did("was", "will be") + " marked with the "
                      "default analysis writing system instead.")
            return base_ws
        return h

    def _run_style(self, run: dict) -> Optional[str]:
        style = run.get("style")
        if not style:
            return None
        if not self._styles_loaded:
            self._styles_loaded = True
            try:
                self._styles = {s.Name for s in self.lp.StylesOC}
            except Exception:
                self._styles = None                 # unknown: apply as given
        if self._styles is not None and style not in self._styles:
            self.warn(f"Character style '{style}' is not in the target project, so text "
                      "using it " + self._did("was imported unstyled.",
                                              "will be imported unstyled."))
            return None
        return style

    # -- references to other lists --------------------------------------------

    def _write_refs(self, obj, item: ItemInfo, label: str) -> None:
        if item.status:
            target = self._find_ref("status", item.status, label)
            if target is not None:
                obj.StatusRA = target
        if item.confidence:
            target = self._find_ref("confidence", item.confidence, label)
            if target is not None:
                obj.ConfidenceRA = target
        for ref in item.researchers:
            target = self._find_ref("researchers", ref, label)
            if target is not None:
                from SIL.LCModel import ICmPerson  # type: ignore
                obj.ResearchersRC.Add(ICmPerson(target))
        for ref in item.restrictions:
            target = self._find_ref("restrictions", ref, label)
            if target is not None:
                obj.RestrictionsRC.Add(target)

    def _find_ref(self, field: str, ref: dict, label: str):
        """Find the referenced item in the target's list: by GUID, then by name."""
        by_guid, by_name = self._ref_lookup(field)
        target = by_guid.get(ref.get("guid", ""))
        if target is None:
            for text in ref.get("name", {}).values():
                target = by_name.get(text.strip().lower())
                if target is not None:
                    break
        if target is None:
            self.warn(f"'{label}': {self._REF_LISTS[field][1]} item "
                      f"'{ref_label(ref)}' is not in the target project, so that "
                      "reference " + self._did("was left out.", "will be left out."))
        return target

    def _ref_lookup(self, field: str) -> Tuple[dict, dict]:
        if field not in self._ref_index:
            by_guid: dict = {}
            by_name: dict = {}

            def walk(seq) -> None:
                for p in seq:
                    by_guid.setdefault(str(p.Guid).lower(), p)
                    for h in self.handles.values():
                        try:
                            text = p.Name.get_String(h).Text
                        except Exception:
                            text = None
                        if text:
                            by_name.setdefault(text.strip().lower(), p)
                    walk(p.SubPossibilitiesOS)

            plist = getattr(self.lp, self._REF_LISTS[field][0], None)
            if plist is not None:
                walk(plist.PossibilitiesOS)
            self._ref_index[field] = (by_guid, by_name)
        return self._ref_index[field]


# ---------------------------------------------------------------------------
# Public: import
# ---------------------------------------------------------------------------

def import_selections(
    project,
    plan: List[Tuple[str, List[ItemInfo]]],
    skip_duplicates: bool = True,
    manage_undo: bool = True,
    warnings: Optional[List[str]] = None,
) -> List[int]:
    """
    Import items into one or more lists in a single transaction.

    plan is [(target_list_guid, items), ...].  Every target list and item is
    checked (see unsupported_reason) before anything is written.

    If ``warnings`` is given, a note is appended for anything that couldn't be
    carried over exactly (see _ItemWriter); the rest of the import goes ahead.

    manage_undo=True  (default) — standalone Tkinter app.
        Wraps the whole import in project.Transaction(), which marks a
        rollback point before the first write.  If any item fails, all
        changes in the import are rolled back automatically.
        Changes are committed to disk when CloseProject() is called.

    manage_undo=False — FLExTools module (FTM_ModifiesDB=True).
        FLExTools already manages the transaction for the whole module run.
        We just write directly; FLExTools handles commit/rollback.

    Returns the number of top-level items added for each plan entry.
    """
    handles = _ws_handles(project)
    prepared = []
    for target_list_guid, items in plan:
        target_list = _find_target_list(project, target_list_guid)
        reason = unsupported_reason(_list_info(project.project, target_list, handles), items)
        if reason:
            raise ValueError(reason)
        existing = _existing_names(target_list) if skip_duplicates else set()
        prepared.append((target_list,
                         [i for i in items if i.name.best().lower() not in existing]))
    if not any(to_import for _, to_import in prepared):
        return [0] * len(prepared)

    writer = _ItemWriter(project, handles, warnings if warnings is not None else [])

    def _do_writes():
        for target_list, to_import in prepared:
            for item in to_import:
                writer.create(target_list.PossibilitiesOS, item)

    if manage_undo:
        # project.Transaction() marks a rollback point; on any exception the
        # whole import is rolled back via LCM's Mark/RollbackToMark API.
        with project.Transaction("Import FLEx list items"):
            _do_writes()
    else:
        # FLExTools module: FLExTools owns the transaction envelope.
        _do_writes()

    return [len(to_import) for _, to_import in prepared]


def import_items(
    project,
    target_list_guid: str,
    items: List[ItemInfo],
    skip_duplicates: bool = True,
    manage_undo: bool = True,
    warnings: Optional[List[str]] = None,
) -> int:
    """Import items into one list (see import_selections).  Returns the number
    of top-level items added."""
    return import_selections(project, [(target_list_guid, items)], skip_duplicates,
                             manage_undo, warnings)[0]


def preflight_import(
    project,
    target_list_guid: str,
    items: List[ItemInfo],
    skip_duplicates: bool = True,
) -> List[str]:
    """
    Check an import against the target project without writing anything.

    Returns notes on what import_items would skip, leave out or simplify:
    top-level items already in the list (with skip_duplicates), writing
    systems or character styles the target lacks, and Status / Confidence /
    People / Restrictions references it can't resolve.  Raises ValueError if
    the target list isn't in the project.
    """
    target_list = _find_target_list(project, target_list_guid)
    existing = _existing_names(target_list) if skip_duplicates else set()
    notes: List[str] = []
    dups = [i.name.best() for i in items if i.name.best().lower() in existing]
    if dups:
        notes.append("Already in the target list (will be skipped): " + ", ".join(dups))
    checker = _ItemWriter(project, _ws_handles(project), notes, preview=True)
    for item in items:
        if item.name.best().lower() not in existing:
            checker.check(item)
    return notes


def _find_target_list(project, target_list_guid: str):
    import System  # type: ignore
    from SIL.LCModel import ICmPossibilityListRepository  # type: ignore

    repo = project.project.ServiceLocator.GetService(ICmPossibilityListRepository)
    target_guid = System.Guid(target_list_guid)
    target_list = next((pl for pl in repo.AllInstances() if pl.Guid == target_guid), None)
    if target_list is None:
        raise ValueError(f"Target list GUID not found in project: {target_list_guid}")
    return target_list


def _list_info(cache, pl, handles: Dict[str, int]) -> ListInfo:
    """ListInfo header (no items) for an LCM list."""
    return ListInfo(guid=str(pl.Guid).lower(), name=_read_ms(pl.Name, handles),
                    abbr=_read_ms(pl.Abbreviation, handles), owner=_owner_field(cache, pl))


def _existing_names(target_list) -> set:
    """Lower-cased names of the list's top-level items (for skip-duplicates)."""
    names: set = set()
    for poss in target_list.PossibilitiesOS:
        try:
            text = poss.Name.BestAnalysisAlternative.Text
            if text:
                names.add(text.lower())
        except Exception:
            pass
    return names


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
      1. GUID — most reliable; most built-in FLEx lists share the same GUID
         across every project (Parts of Speech, Semantic Domains, etc.).
      2. Owning field — a built-in list is the only one in its field (e.g.
         DsDiscourseData.ChartMarkers for Text Chart Markers), which finds it
         even in projects where FLEx gave the list its own GUID.
      3. Display name — fallback for custom lists or cross-version projects.

    Returns (matched_list, match_type) where match_type is one of:
      'guid'  — matched by GUID
      'owner' — matched by owning field (no GUID match)
      'name'  — matched by display name (no GUID or owner match)
      'none'  — no match found
    """
    if source_list.guid:
        for li in target_lists:
            if li.guid == source_list.guid:
                return li, "guid"

    if source_list.owner:
        same_owner = [li for li in target_lists if li.owner == source_list.owner]
        if len(same_owner) == 1:
            return same_owner[0], "owner"

    src_name = source_list.name.best().lower().strip()
    if src_name:
        for li in target_lists:
            if li.name.best().lower().strip() == src_name:
                return li, "name"

    return None, "none"


# ---------------------------------------------------------------------------
# Public: JSON transfer format
#
# A transfer file opens with a version statement:
#     "format": "flex-list-migrator", "format_version": 3
# Version 3 holds one or more lists:
#     "lists": [{"source_list_guid", "source_list_name", "source_list_owner",
#                "items": [...]}, ...]
# Versions 1 and 2 hold one list, with those fields at the top level.  Files
# from 1.0.x say "format": "flex-list-migrator-v1" instead (name/abbr/desc/
# daughters only); version 2 (1.1) added desc_runs, discussion, status,
# confidence, researchers, restrictions and source_list_owner.  A file with
# one list is still written as version 2, so FLEx List Migrator 1.1 can
# open it.  TRANSFER_FORMAT.md describes every field.
# ---------------------------------------------------------------------------

FORMAT_NAME = "flex-list-migrator"
FORMAT_VERSION = 3                     # newest version this release reads and writes
_V1_FORMAT = "flex-list-migrator-v1"   # how version 1 files identify themselves

_LIST_KEYS = {"source_list_guid", "source_list_name", "source_list_owner", "items"}
_TOP_KEYS = {"format", "format_version", "generator", "source_project", "description",
             "lists"} | _LIST_KEYS
_V2_ITEM_KEYS = {"desc_runs", "discussion", "status", "confidence",
                 "researchers", "restrictions"}
_ITEM_KEYS = {"original_guid", "cls", "name", "abbr", "desc", "daughters"} | _V2_ITEM_KEYS
_REF_KEYS = {"guid", "name"}
_RUN_KEYS = {"text", "ws", "style"}


class TransferFileError(ValueError):
    """A transfer file that can't be used; ``problems`` lists why."""

    def __init__(self, summary: str, problems: List[str] = ()):
        self.problems = list(problems)
        shown = self.problems[:15]
        text = summary
        if shown:
            text += "\n\n• " + "\n• ".join(shown)
        if len(self.problems) > len(shown):
            text += f"\n• …and {len(self.problems) - len(shown)} more"
        super().__init__(text)


def format_version(data: dict) -> Optional[int]:
    """The version a transfer file declares: None if it isn't a transfer
    file at all, 0 if it is but the version statement is unreadable."""
    fmt = data.get("format")
    if fmt == _V1_FORMAT:
        return 1
    if fmt == FORMAT_NAME:
        v = data.get("format_version")
        return v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else 0
    return None


def validate_transfer(data: object) -> Tuple[List[str], List[str]]:
    """
    Check a parsed transfer file before any of it is used.

    Returns (errors, warnings).  Any error means the file must not be loaded;
    warnings describe things that will be ignored or adjusted.  Problems are
    located by path, e.g. lists[1].items[0].daughters[2].discussion[1].
    """
    errors: List[str] = []
    warnings: List[str] = []
    if not isinstance(data, dict):
        return ["The file must hold a JSON object ({ … }) at the top level."], warnings
    version = format_version(data)
    if version is None:
        return ['This is not a FLEx List Migrator transfer file: it has no '
                f'"format": "{FORMAT_NAME}" statement.'], warnings
    if version == 0:
        return ['"format_version" must be a whole number such as '
                f'{FORMAT_VERSION}.'], warnings
    if version > FORMAT_VERSION:
        return [f"This file uses transfer format version {version}, but this copy of "
                f"FLEx List Migrator reads versions 1 to {FORMAT_VERSION}. Update FLEx "
                "List Migrator to load it."], warnings

    for key in data:
        if key not in _TOP_KEYS:
            warnings.append(f'Unknown top-level field "{key}" will be ignored.')
    for key in ("generator", "source_project", "description"):
        if key in data and not isinstance(data[key], str):
            errors.append(f'"{key}" must be text.')

    seen: set = set()
    newer_fields: set = set()
    if version >= 3:
        if "items" in data:
            errors.append('In format version 3, items go inside "lists", not at the top level.')
        lists = data.get("lists")
        if not isinstance(lists, list) or not lists:
            errors.append('"lists" must be a non-empty list of lists.')
            return errors, warnings
        for i, entry in enumerate(lists):
            where = f"lists[{i}]"
            if not isinstance(entry, dict):
                errors.append(f"{where} must be an object ({{ … }}).")
                continue
            for key in entry:
                if key not in _LIST_KEYS:
                    warnings.append(f'{where}: unknown field "{key}" will be ignored.')
            _check_list(entry, where + ".", errors, warnings, seen, newer_fields)
    else:
        if "lists" in data:
            errors.append(f'"lists" needs format version 3; this file says version {version}.')
        _check_list(data, "", errors, warnings, seen, newer_fields)
        if version == 1 and newer_fields:
            warnings.append("The file says it is format version 1 but uses version 2 fields ("
                            + ", ".join(sorted(newer_fields)) + "); they will be read anyway.")
    return errors, warnings


def _check_list(entry: dict, prefix: str, errors: List[str], warnings: List[str],
                seen: set, newer_fields: set) -> None:
    """Check one list's header fields and items; prefix locates it, e.g. "lists[1].\""""
    for key in ("source_list_guid", "source_list_owner"):
        if key in entry and not isinstance(entry[key], str):
            errors.append(f'{prefix}{key} must be text.')
    if "source_list_name" in entry:
        _check_multistr(entry["source_list_name"], f"{prefix}source_list_name", errors)
    items = entry.get("items")
    if not isinstance(items, list) or not items:
        errors.append(f'{prefix}items must be a non-empty list of list items.')
        return
    for j, item in enumerate(items):
        _check_item(item, f"{prefix}items[{j}]", errors, warnings, seen, newer_fields)


def _check_multistr(value: object, path: str, errors: List[str]) -> None:
    if not (isinstance(value, dict)
            and all(isinstance(k, str) and isinstance(v, str) for k, v in value.items())):
        errors.append(f'{path} must map writing systems to text, e.g. {{"en": "…"}}.')


def _check_runs(value: object, path: str, errors: List[str], warnings: List[str]) -> None:
    if isinstance(value, str):
        return
    if not isinstance(value, list):
        errors.append(f'{path} must be text or a list of runs like {{"text": "…", "ws": "en"}}.')
        return
    for j, run in enumerate(value):
        where = f"{path}[{j}]"
        if isinstance(run, str):
            continue
        if not isinstance(run, dict) or not isinstance(run.get("text"), str):
            errors.append(f'{where} must be text or an object with a "text" field.')
            continue
        for key in ("ws", "style"):
            if key in run and not isinstance(run[key], str):
                errors.append(f'{where}.{key} must be text.')
        for key in run:
            if key not in _RUN_KEYS:
                warnings.append(f'{where}: unknown field "{key}" will be ignored.')


def _check_ref(value: object, path: str, errors: List[str], warnings: List[str]) -> None:
    if isinstance(value, str) and value.strip():
        return                                          # a bare name
    if not isinstance(value, dict):
        errors.append(f'{path} must be a name, or an object with "guid" and/or "name".')
        return
    if "guid" in value and not isinstance(value["guid"], str):
        errors.append(f"{path}.guid must be text.")
    if "name" in value:
        _check_multistr(value["name"], f"{path}.name", errors)
    if not value.get("guid") and not value.get("name"):
        errors.append(f'{path} needs a "guid" or a "name".')
    for key in value:
        if key not in _REF_KEYS:
            warnings.append(f'{path}: unknown field "{key}" will be ignored.')


def _check_item(item: object, path: str, errors: List[str], warnings: List[str],
                seen: set, newer_fields: set) -> None:
    if not isinstance(item, dict):
        errors.append(f"{path} must be an object ({{ … }}).")
        return
    name = item.get("name")
    names = [v for v in name.values() if isinstance(v, str) and v.strip()] \
        if isinstance(name, dict) else []
    where = f"{path} ({names[0]})" if names else path
    for key in item:
        if key not in _ITEM_KEYS:
            warnings.append(f'{where}: unknown field "{key}" will be ignored.')
    newer_fields.update(_V2_ITEM_KEYS & set(item))
    for key in ("name", "abbr", "desc"):
        if key in item:
            _check_multistr(item[key], f"{where}.{key}", errors)
    if isinstance(name, dict) and not names:
        warnings.append(f"{where} has no name, so it will be imported unnamed.")
    cls = item.get("cls", "CmPossibility")
    if not isinstance(cls, str):
        errors.append(f"{where}.cls must be text.")
    elif norm_cls(cls) not in SUPPORTED_ITEM_CLASSES:
        msg = (f"Items of class '{cls}' can't be imported by this version; support "
               "may come in a future release.")
        if msg not in warnings:
            warnings.append(msg)
    guid = item.get("original_guid", "")
    if not isinstance(guid, str):
        errors.append(f"{where}.original_guid must be text.")
    elif guid and guid in seen:
        warnings.append(f"{where}: original_guid {guid} is used more than once; "
                        "the repeat gets a new one.")
    seen.add(guid)
    desc_runs = item.get("desc_runs", {})
    if not isinstance(desc_runs, dict):
        errors.append(f'{where}.desc_runs must map writing systems to runs.')
    else:
        for code, runs in desc_runs.items():
            _check_runs(runs, f"{where}.desc_runs.{code}", errors, warnings)
    discussion = item.get("discussion", [])
    if not isinstance(discussion, list):
        errors.append(f"{where}.discussion must be a list of paragraphs.")
    else:
        for j, para in enumerate(discussion):
            _check_runs(para, f"{where}.discussion[{j}]", errors, warnings)
    for key in ("status", "confidence"):
        if item.get(key) is not None:
            _check_ref(item[key], f"{where}.{key}", errors, warnings)
    for key in ("researchers", "restrictions"):
        refs = item.get(key, [])
        if not isinstance(refs, list):
            errors.append(f"{where}.{key} must be a list.")
            continue
        for j, ref in enumerate(refs):
            _check_ref(ref, f"{where}.{key}[{j}]", errors, warnings)
    daughters = item.get("daughters", [])
    if not isinstance(daughters, list):
        errors.append(f"{where}.daughters must be a list.")
        return
    for j, daughter in enumerate(daughters):
        _check_item(daughter, f"{path}.daughters[{j}]", errors, warnings, seen, newer_fields)


def save_transfer(
    selections: List[Tuple[ListInfo, List[ItemInfo]]],
    source_project_name: str,
    out_path: str | Path,
    description: str = "",
) -> int:
    """
    Write one or more lists' items to a transfer file.

    One list is written as format version 2, which FLEx List Migrator 1.1
    can open; several lists need version 3.  Returns the version written.
    description, if given, is saved as the file's "description" (templates
    are listed by it).  Raises ValueError if nothing is selected, or for a
    list (or items) this release can't export — see SUPPORTED_LISTS.
    """
    selections = [(li, items) for li, items in selections if items]
    if not selections:
        raise ValueError("Nothing to save: no items are checked.")
    for li, items in selections:
        reason = unsupported_reason(li, items)
        if reason:
            raise ValueError(reason)

    def header(li: ListInfo) -> dict:
        return {"source_list_guid": li.guid, "source_list_name": li.name.to_dict(),
                "source_list_owner": li.owner}

    version = 2 if len(selections) == 1 else 3
    data = {
        "format": FORMAT_NAME,
        "format_version": version,
        "generator": "FLEx List Migrator" + (f" {_app_version()}" if _app_version() else ""),
        "source_project": source_project_name,
    }
    if description:
        data["description"] = description
    if version == 2:
        li, items = selections[0]
        data.update(header(li))
        data["items"] = [i.to_dict() for i in items]
    else:
        data["lists"] = [dict(header(li), items=[i.to_dict() for i in items])
                         for li, items in selections]
    errors, _warnings = validate_transfer(data)
    if errors:   # a bug here, not bad input: refuse to write a file we can't read
        raise TransferFileError("The transfer file could not be written:", errors)
    Path(out_path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return version


def save_to_json(
    items: List[ItemInfo],
    source_list: ListInfo,
    source_project_name: str,
    out_path: str | Path,
) -> None:
    """Write one list's items to a transfer file (see save_transfer)."""
    save_transfer([(source_list, items)], source_project_name, out_path)


def load_from_json(path: str | Path) -> Tuple[dict, List[ListInfo], List[str]]:
    """
    Read and check a transfer file (any version from 1 to FORMAT_VERSION).

    Returns (metadata, lists, warnings): one ListInfo per list in the file,
    holding its items.  metadata["format_version"] is the version the file
    declared.  Raises TransferFileError, listing every problem found, if the
    file can't be used — nothing is loaded from it then.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8-sig")   # tolerate a BOM
    except UnicodeDecodeError:
        raise TransferFileError("The file is not UTF-8 text, so it can't be a "
                                "transfer file.") from None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TransferFileError(f"The file is not valid JSON (line {exc.lineno}, "
                                f"column {exc.colno}: {exc.msg}).") from None
    errors, warnings = validate_transfer(data)
    if errors:
        raise TransferFileError("This transfer file has problems, so nothing was "
                                "loaded from it:", errors)
    version = format_version(data)
    lists: List[ListInfo] = []
    seen: set = set()
    for entry in (data["lists"] if version >= 3 else [data]):
        li = ListInfo(
            guid=str(entry.get("source_list_guid") or "").lower(),
            name=MultiStr.from_dict(entry.get("source_list_name", {})),
            items=[ItemInfo.from_dict(d) for d in entry["items"]],
            owner=entry.get("source_list_owner") or "",
        )
        _ensure_unique_ids(li.items, seen)
        lists.append(li)
    meta = {k: v for k, v in data.items() if k not in ("items", "lists")}
    meta["format_version"] = version
    return meta, lists, warnings


def _ensure_unique_ids(items: List[ItemInfo], seen: set) -> None:
    """Give items with a missing or repeated original_guid a fresh one.

    original_guid only identifies items within this tool (the import makes new
    FLEx objects with their own GUIDs), so hand-made files may leave it out.
    """
    for item in items:
        if not item.original_guid or item.original_guid in seen:
            item.original_guid = str(uuid.uuid4())
        seen.add(item.original_guid)
        _ensure_unique_ids(item.daughters, seen)


def _app_version() -> str:
    try:
        from version import __version__  # type: ignore
        return __version__
    except Exception:
        return ""


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
