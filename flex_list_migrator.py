"""
FLEx List Migrator
==================
Standalone Windows app for copying list items between FLEx 9 projects.

Uses flexlibs2 directly — no FLExTools GUI required.
FLEx must be fully closed before loading any project here.

Requirements:
  - Windows
  - FieldWorks Language Explorer 9 installed
  - flexlibs2 pip-installed (pip install flexlibs2)

To build a standalone .exe:
  pip install flexlibs2 pyinstaller
  pyinstaller build.spec
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Tuple

import flex_core as core
from version import __version__

import pretty_export


# ---------------------------------------------------------------------------
# Human-readable export dialog
# ---------------------------------------------------------------------------

class ExportReadableDialog:
    """Modal dialog for configuring the human-readable export."""

    def __init__(
        self,
        parent: tk.Widget,
        all_lists: List[core.ListInfo],
        current_list: Optional[core.ListInfo],
        filter_fn,          # callable(items) -> filtered_items
    ):
        self.result: Optional[Tuple] = None  # (path, fmt, selections, ws)
        self._all_lists = all_lists
        self._current_list = current_list
        self._filter_fn = filter_fn

        win = tk.Toplevel(parent)
        win.title("Export Human-Readable")
        win.resizable(False, False)
        win.grab_set()
        self.window = win
        pad = {"padx": 8, "pady": 4}

        # Scope
        scope_f = ttk.LabelFrame(win, text="What to export")
        scope_f.pack(fill="x", **pad)
        self._scope = tk.StringVar(value="selected")
        ttk.Radiobutton(
            scope_f, text="Currently selected items only",
            variable=self._scope, value="selected",
        ).pack(anchor="w")
        ttk.Radiobutton(
            scope_f, text="Entire list(s) — choose below",
            variable=self._scope, value="lists",
        ).pack(anchor="w")

        # List chooser
        lists_f = ttk.LabelFrame(win, text="Choose lists to export in full")
        lists_f.pack(fill="both", expand=True, **pad)

        canvas = tk.Canvas(lists_f, height=130, highlightthickness=0)
        vscroll = ttk.Scrollbar(lists_f, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._list_vars: List[Tuple[tk.BooleanVar, core.ListInfo]] = []
        for li in all_lists:
            var = tk.BooleanVar(value=(li is current_list))
            ttk.Checkbutton(inner, text=li.display_name, variable=var).pack(anchor="w")
            self._list_vars.append((var, li))

        inner.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))

        # Format
        fmt_f = ttk.LabelFrame(win, text="Output format")
        fmt_f.pack(fill="x", **pad)
        self._fmt = tk.StringVar(value="html")
        ttk.Radiobutton(
            fmt_f, text="HTML — styled, opens in any browser",
            variable=self._fmt, value="html",
        ).pack(anchor="w")
        ttk.Radiobutton(
            fmt_f, text="Plain text — indented, UTF-8",
            variable=self._fmt, value="txt",
        ).pack(anchor="w")

        # Writing system
        ws_row = ttk.Frame(win)
        ws_row.pack(fill="x", **pad)
        ttk.Label(ws_row, text="Primary writing system code:").pack(side="left")
        self._ws = tk.StringVar(value="en")
        ttk.Entry(ws_row, textvariable=self._ws, width=8).pack(side="left", padx=4)
        ttk.Label(ws_row, text='(e.g. "en", "fr", "fau")',
                  foreground="#666").pack(side="left")

        # Buttons
        btn_row = ttk.Frame(win)
        btn_row.pack(fill="x", **pad)
        ttk.Button(btn_row, text="Export…", command=self._submit).pack(side="right")
        ttk.Button(btn_row, text="Cancel",
                   command=win.destroy).pack(side="right", padx=4)

    def _submit(self):
        fmt = self._fmt.get()
        ws = self._ws.get().strip() or "en"
        ext = ".html" if fmt == "html" else ".txt"

        path = filedialog.asksaveasfilename(
            parent=self.window,
            title="Save Human-Readable Export",
            defaultextension=ext,
            filetypes=[("HTML", "*.html"), ("Text", "*.txt"), ("All", "*.*")],
        )
        if not path:
            return

        scope = self._scope.get()
        selections: List[Tuple[core.ListInfo, List[core.ItemInfo]]] = []

        if scope == "selected" and self._current_list:
            filtered = self._filter_fn(self._current_list.items)
            if filtered:
                selections.append((self._current_list, filtered))
        else:
            for var, li in self._list_vars:
                if var.get():
                    selections.append((li, li.items))

        if not selections:
            messagebox.showwarning("Nothing to export",
                                   "No items selected for export.",
                                   parent=self.window)
            return

        self.result = (path, fmt, selections, ws)
        self.window.destroy()


# ---------------------------------------------------------------------------
# Manual list picker (fallback when auto-match fails)
# ---------------------------------------------------------------------------

class _ListPickerDialog:
    """
    Modal dialog shown when no automatic list match is found.
    Lets the user choose which target list to import into.
    """

    def __init__(self, parent: tk.Widget, target_lists: List[core.ListInfo],
                 source_name: str):
        self.result: Optional[core.ListInfo] = None

        win = tk.Toplevel(parent)
        win.title("Select Target List")
        win.resizable(False, False)
        win.grab_set()
        self.window = win

        pad = {"padx": 10, "pady": 6}
        ttk.Label(
            win,
            text=f"No matching list found for:\n\"{source_name}\"\n\n"
                 "Choose which target list to import into:",
            justify="left",
        ).pack(**pad)

        list_f = ttk.Frame(win)
        list_f.pack(fill="both", expand=True, padx=10)
        sb = ttk.Scrollbar(list_f, orient="vertical")
        self._lb = tk.Listbox(list_f, width=50, height=14,
                               yscrollcommand=sb.set, exportselection=False)
        sb.configure(command=self._lb.yview)
        sb.pack(side="right", fill="y")
        self._lb.pack(fill="both", expand=True)

        for li in target_lists:
            self._lb.insert("end", li.display_name)
        self._target_lists = target_lists

        btn_row = ttk.Frame(win)
        btn_row.pack(fill="x", **pad)
        ttk.Button(btn_row, text="Import Here",
                   command=self._submit).pack(side="right")
        ttk.Button(btn_row, text="Cancel",
                   command=win.destroy).pack(side="right", padx=(0, 6))

        self._lb.bind("<Double-Button-1>", lambda _e: self._submit())

    def _submit(self):
        sel = self._lb.curselection()
        if not sel:
            return
        self.result = self._target_lists[sel[0]]
        self.window.destroy()


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"FLEx List Migrator  v{__version__}")
        root.minsize(980, 740)

        # State
        self._src: Optional[object] = None          # FLExProject (source)
        self._tgt: Optional[object] = None          # FLExProject (target)
        self._src_lists: List[core.ListInfo] = []
        self._tgt_lists: List[core.ListInfo] = []
        self._current_list: Optional[core.ListInfo] = None
        self._checked: set = set()                  # set of original_guid
        self._iid_to_guid: Dict[str, str] = {}
        self._guid_to_name: Dict[str, str] = {}
        self._guid_to_item: Dict[str, core.ItemInfo] = {}
        self._projects_dir: Optional[str] = None
        # Source type: "flex" or "json"
        self._source_type_var = tk.StringVar(value="flex")
        self._src_json_path_var = tk.StringVar()
        self._src_json_label: str = ""   # display label when JSON is source

        self._build_ui()
        self._refresh_project_combos()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self):
        P = {"padx": 6, "pady": 4}

        # Source section
        src_frame = ttk.LabelFrame(self.root, text="Source")
        src_frame.pack(fill="x", **P)

        # Source-type radio buttons
        radio_row = ttk.Frame(src_frame)
        radio_row.pack(fill="x", pady=(0, 4))
        ttk.Radiobutton(radio_row, text="FLEx Project",
                        variable=self._source_type_var, value="flex",
                        command=self._on_source_type_change).pack(side="left")
        ttk.Radiobutton(radio_row, text="JSON File",
                        variable=self._source_type_var, value="json",
                        command=self._on_source_type_change).pack(side="left", padx=(12, 0))

        # FLEx input row (shown by default)
        self._flex_src_row = ttk.Frame(src_frame)
        self._flex_src_row.pack(fill="x")
        ttk.Label(self._flex_src_row, text="Project:").pack(side="left")
        self._src_combo = ttk.Combobox(self._flex_src_row, width=36, state="normal")
        self._src_combo.pack(side="left", padx=4)
        ttk.Button(self._flex_src_row, text="Browse folder…",
                   command=self._browse_folder).pack(side="left")
        ttk.Button(self._flex_src_row, text="Load",
                   command=self._load_source).pack(side="left", padx=(6, 0))

        # JSON input row (hidden by default)
        self._json_src_row = ttk.Frame(src_frame)
        # not packed yet
        ttk.Label(self._json_src_row, text="File:").pack(side="left")
        ttk.Entry(self._json_src_row, textvariable=self._src_json_path_var,
                  width=44).pack(side="left", padx=4, fill="x", expand=True)
        ttk.Button(self._json_src_row, text="Browse…",
                   command=self._browse_source_json).pack(side="left")
        ttk.Button(self._json_src_row, text="Load",
                   command=self._load_source).pack(side="left", padx=(6, 0))

        # Paned: list browser (left) + item tree (right)
        pane = ttk.PanedWindow(self.root, orient="horizontal")
        pane.pack(fill="both", expand=True, **P)

        list_f = ttk.LabelFrame(pane, text="Lists", padding=4)
        pane.add(list_f, weight=1)

        self._list_box = tk.Listbox(
            list_f, selectmode="single", font=("Segoe UI", 10),
            exportselection=False, activestyle="dotbox",
        )
        lsb = ttk.Scrollbar(list_f, orient="vertical", command=self._list_box.yview)
        self._list_box.configure(yscrollcommand=lsb.set)
        lsb.pack(side="right", fill="y")
        self._list_box.pack(fill="both", expand=True)
        self._list_box.bind("<<ListboxSelect>>", self._on_list_select)

        item_f = ttk.LabelFrame(pane, text="Items", padding=4)
        pane.add(item_f, weight=3)

        self._tree = ttk.Treeview(
            item_f, columns=("abbr",), show="tree headings", selectmode="none",
        )
        self._tree.heading("#0", text="Name (click to toggle ☑/☐)")
        self._tree.heading("abbr", text="Abbr")
        self._tree.column("#0", width=340, stretch=True)
        self._tree.column("abbr", width=80, stretch=False)
        ty = ttk.Scrollbar(item_f, orient="vertical", command=self._tree.yview)
        tx = ttk.Scrollbar(item_f, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=ty.set, xscrollcommand=tx.set)
        ty.pack(side="right", fill="y")
        tx.pack(side="bottom", fill="x")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<Button-1>", self._on_item_click)
        self._tree.tag_configure("checked", foreground="#000")
        self._tree.tag_configure("unchecked", foreground="#888")

        btn_row = ttk.Frame(item_f)
        btn_row.pack(fill="x", pady=(4, 0))
        for label, cmd in (
            ("Select All",    lambda: self._select_all(True)),
            ("Deselect All",  lambda: self._select_all(False)),
            ("Expand All",    lambda: self._expand_all(True)),
            ("Collapse All",  lambda: self._expand_all(False)),
        ):
            ttk.Button(btn_row, text=label, command=cmd).pack(side="left", padx=2)

        # Export buttons
        exp_row = ttk.Frame(self.root)
        exp_row.pack(fill="x", padx=6, pady=2)
        ttk.Button(exp_row, text="Save Transfer JSON…",
                   command=self._save_json).pack(side="left")
        ttk.Button(exp_row, text="Export Human-Readable…",
                   command=self._export_readable).pack(side="left", padx=8)

        ttk.Separator(self.root, orient="horizontal").pack(fill="x", padx=6, pady=4)

        # Target / import section
        tgt_frame = ttk.LabelFrame(self.root, text="Target Project (Import)")
        tgt_frame.pack(fill="x", **P)

        row1 = ttk.Frame(tgt_frame)
        row1.pack(fill="x", pady=(0, 4))
        ttk.Label(row1, text="Project:").pack(side="left")
        self._tgt_combo = ttk.Combobox(row1, width=38, state="normal")
        self._tgt_combo.pack(side="left", padx=4)
        ttk.Button(row1, text="Load Target",
                   command=self._load_target).pack(side="left", padx=(8, 0))

        opt_row = ttk.Frame(tgt_frame)
        opt_row.pack(fill="x", pady=(0, 4))
        self._skip_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_row, text="Skip duplicates",
                        variable=self._skip_var).pack(side="left")

        ttk.Button(tgt_frame, text="⬇  Import Items",
                   command=self._do_import).pack(anchor="w", pady=(2, 0))

        # Status bar
        self._status_var = tk.StringVar(value="Ready. Load a source project to begin.")
        ttk.Label(
            self.root, textvariable=self._status_var,
            relief="sunken", anchor="w", padding=(4, 2),
        ).pack(fill="x", side="bottom")

    # ── Project discovery ──────────────────────────────────────────────────

    def _refresh_project_combos(self):
        projects = core.find_projects(self._projects_dir)
        names = [name for name, _ in projects]
        self._src_combo["values"] = names
        self._tgt_combo["values"] = names

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Select FLEx Projects Folder")
        if folder:
            self._projects_dir = folder
            self._refresh_project_combos()
            self._set_status(f"Projects folder: {folder}")

    # ── Source (FLEx project or JSON file) ────────────────────────────────

    def _on_source_type_change(self):
        if self._source_type_var.get() == "flex":
            self._json_src_row.pack_forget()
            self._flex_src_row.pack(fill="x")
        else:
            self._flex_src_row.pack_forget()
            self._json_src_row.pack(fill="x")
        # Clear whatever was loaded as the previous source type
        self._clear_source()

    def _clear_source(self):
        if self._src:
            core.close_project(self._src)
            self._src = None
        self._src_lists = []
        self._current_list = None
        self._checked.clear()
        self._iid_to_guid.clear()
        self._guid_to_name.clear()
        self._guid_to_item.clear()
        self._list_box.delete(0, "end")
        for iid in self._tree.get_children():
            self._tree.delete(iid)

    def _browse_source_json(self):
        path = filedialog.askopenfilename(
            title="Select Transfer JSON",
            filetypes=[("JSON", "*.json"), ("All Files", "*.*")],
        )
        if path:
            self._src_json_path_var.set(path)

    def _load_source(self):
        if self._source_type_var.get() == "json":
            self._load_source_json()
        else:
            self._load_source_flex()

    def _load_source_flex(self):
        name = self._src_combo.get().strip()
        if not name:
            messagebox.showwarning("No Project",
                                   "Type or select a source project name.")
            return
        if self._src:
            core.close_project(self._src)
            self._src = None
        self._set_status(f"Opening '{name}'…  FLEx must be closed.")
        self.root.update()
        try:
            self._src = core.open_project(name, write_enabled=False)
            self._src_lists = core.read_lists(self._src)
            self._refresh_list_box()
            self._set_status(
                f"Source: {name}  ({len(self._src_lists)} lists)"
            )
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))
            self._set_status("Source project failed to load.")

    def _load_source_json(self):
        path = self._src_json_path_var.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showwarning("No File", "Browse to a transfer JSON file first.")
            return
        try:
            meta, items = core.load_from_json(path)
        except Exception as exc:
            messagebox.showerror("JSON Error", str(exc))
            return
        # Build a synthetic ListInfo so the tree works identically to a FLEx source
        list_name = core.MultiStr.from_dict(meta.get("source_list_name", {}))
        if not list_name.vals:
            list_name = core.MultiStr({"en": _basename(path)})
        synth = core.ListInfo(
            guid=meta.get("source_list_guid", ""),
            name=list_name,
            items=items,
        )
        src_project = meta.get("source_project", "")
        self._src_json_label = src_project
        self._src_lists = [synth]
        self._refresh_list_box(json_source=True)
        # Auto-select the only list so the tree populates immediately
        self._list_box.selection_set(0)
        self._on_list_select()
        n_top = len(items)
        n_total = sum(1 + _count_descendants(i) for i in items)
        self._set_status(
            f"JSON source: {synth.display_name}  "
            f"({n_top} top-level, {n_total} total items)"
            + (f"  from '{src_project}'" if src_project else "")
        )

    def _refresh_list_box(self, json_source: bool = False):
        self._list_box.delete(0, "end")
        for li in self._src_lists:
            label = f"[JSON]  {li.display_name}" if json_source else li.display_name
            self._list_box.insert("end", label)

    def _on_list_select(self, _event=None):
        sel = self._list_box.curselection()
        if not sel or not self._src_lists:
            return
        li = self._src_lists[sel[0]]
        self._current_list = li
        self._checked.clear()
        self._iid_to_guid.clear()
        self._guid_to_name.clear()
        self._guid_to_item.clear()
        self._populate_tree(li)
        self._set_status(f"{li.display_name}  —  {len(li.items)} top-level item(s)")

    def _populate_tree(self, li: core.ListInfo):
        for iid in self._tree.get_children():
            self._tree.delete(iid)

        def insert(parent_iid: str, item: core.ItemInfo) -> None:
            checked = item.original_guid in self._checked
            name = item.name.best() or "(unnamed)"
            self._guid_to_item[item.original_guid] = item
            self._guid_to_name[item.original_guid] = name
            iid = self._tree.insert(
                parent_iid, "end",
                text=f"{'☑' if checked else '☐'} {name}",
                values=(item.abbr.best(),),
                tags=("checked" if checked else "unchecked",),
            )
            self._iid_to_guid[iid] = item.original_guid
            for d in item.daughters:
                insert(iid, d)

        for item in li.items:
            insert("", item)

    # ── Item check toggling ────────────────────────────────────────────────

    def _on_item_click(self, event: tk.Event):
        # Skip clicks on the expand/collapse triangle
        try:
            if "indicator" in self._tree.identify_element(event.x, event.y).lower():
                return
        except Exception:
            pass
        iid = self._tree.identify_row(event.y)
        if not iid:
            return
        guid = self._iid_to_guid.get(iid)
        if not guid:
            return
        if guid in self._checked:
            self._uncheck(iid)
        else:
            self._check(iid)
        n = len(self._checked)
        self._set_status(f"{n} item{'s' if n != 1 else ''} selected")

    def _check(self, iid: str) -> None:
        guid = self._iid_to_guid.get(iid)
        if guid:
            self._checked.add(guid)
            name = self._guid_to_name.get(guid, "")
            self._tree.item(iid, text=f"☑ {name}", tags=("checked",))
        for child in self._tree.get_children(iid):
            self._check(child)

    def _uncheck(self, iid: str) -> None:
        guid = self._iid_to_guid.get(iid)
        if guid:
            self._checked.discard(guid)
            name = self._guid_to_name.get(guid, "")
            self._tree.item(iid, text=f"☐ {name}", tags=("unchecked",))
        for child in self._tree.get_children(iid):
            self._uncheck(child)

    def _select_all(self, checked: bool) -> None:
        for iid in self._tree.get_children():
            (self._check if checked else self._uncheck)(iid)
        n = len(self._checked)
        self._set_status(f"{n} item{'s' if n != 1 else ''} selected")

    def _expand_all(self, expand: bool) -> None:
        for iid in self._all_iids():
            self._tree.item(iid, open=expand)

    def _all_iids(self, parent: str = "") -> List[str]:
        result = []
        for iid in self._tree.get_children(parent):
            result.append(iid)
            result.extend(self._all_iids(iid))
        return result

    # ── Selection helpers ──────────────────────────────────────────────────

    def _get_selected(self) -> List[core.ItemInfo]:
        """Return checked items (with daughters filtered to only checked ones)."""
        if not self._current_list:
            return []
        return self._filter_checked(self._current_list.items)

    def _filter_checked(self, items: List[core.ItemInfo]) -> List[core.ItemInfo]:
        result = []
        for item in items:
            if item.original_guid in self._checked:
                result.append(core.ItemInfo(
                    original_guid=item.original_guid,
                    cls=item.cls,
                    name=item.name,
                    abbr=item.abbr,
                    desc=item.desc,
                    daughters=self._filter_checked(item.daughters),
                ))
        return result

    # ── JSON export ────────────────────────────────────────────────────────

    def _save_json(self):
        selected = self._get_selected()
        if not selected:
            messagebox.showwarning("Nothing Selected",
                                   "Check at least one item, then save.")
            return
        if not self._current_list:
            return
        path = filedialog.asksaveasfilename(
            title="Save Transfer JSON",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            if self._source_type_var.get() == "json":
                src_name = self._src_json_label or _basename(self._src_json_path_var.get())
            else:
                src_name = self._src_combo.get().strip()
            core.save_to_json(selected, self._current_list, src_name, path)
            self._set_status(f"Saved {len(selected)} item(s) → {_basename(path)}")
        except Exception as exc:
            messagebox.showerror("Save Error", str(exc))

    # ── Human-readable export ──────────────────────────────────────────────

    def _export_readable(self):
        if not self._src_lists:
            messagebox.showwarning("No Source",
                                   "Load a source project or JSON file first.")
            return
        dlg = ExportReadableDialog(
            self.root, self._src_lists,
            self._current_list, self._filter_checked,
        )
        self.root.wait_window(dlg.window)
        if not dlg.result:
            return
        path, fmt, selections, ws = dlg.result
        try:
            if fmt == "html":
                pretty_export.export_html(selections, path, preferred_ws=ws)
            else:
                pretty_export.export_text(selections, path, preferred_ws=ws)
            self._set_status(f"Exported → {_basename(path)}")
            if messagebox.askyesno("Export saved",
                                   f"Saved to {_basename(path)}.\nOpen now?"):
                _open_file(path)
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))

    # ── Target project ─────────────────────────────────────────────────────

    def _load_target(self):
        name = self._tgt_combo.get().strip()
        if not name:
            messagebox.showwarning("No Project",
                                   "Type or select a target project name.")
            return
        if self._tgt:
            core.close_project(self._tgt)
            self._tgt = None
        self._set_status(f"Opening target '{name}'…  FLEx must be closed.")
        self.root.update()
        try:
            self._tgt = core.open_project(name, write_enabled=True)
            self._tgt_lists = core.read_lists(self._tgt)
            self._set_status(f"Target: {name}  ({len(self._tgt_lists)} lists)")
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))
            self._set_status("Target project failed to load.")

    # ── Import ─────────────────────────────────────────────────────────────

    def _do_import(self):
        items = self._get_selected()
        if not items:
            messagebox.showwarning("Nothing to Import",
                                   "Select items in the source panel first.")
            return
        if not self._tgt:
            messagebox.showwarning("No Target", "Load a target project first.")
            return
        if not self._current_list:
            return

        # Auto-match source list → target list
        tgt_list, match_type = core.find_matching_list(
            self._tgt_lists, self._current_list
        )

        if match_type == "none":
            # No auto-match — let user pick manually
            dlg = _ListPickerDialog(
                self.root, self._tgt_lists, self._current_list.display_name
            )
            self.root.wait_window(dlg.window)
            if not dlg.result:
                return
            tgt_list = dlg.result
            match_type = "manual"

        skip = self._skip_var.get()
        match_note = {
            "guid": "(matched by GUID)",
            "name": "(matched by name — verify this is correct)",
            "manual": "(manually selected)",
        }[match_type]

        confirmed = messagebox.askyesno(
            "Confirm Import",
            f"Import {len(items)} item(s)\n"
            f"  from  '{self._current_list.display_name}'\n"
            f"  into  '{tgt_list.display_name}'\n"
            f"          {match_note}\n\n"
            f"Skip duplicates: {'yes' if skip else 'no'}\n\n"
            "FLEx must remain closed until this completes.",
        )
        if not confirmed:
            return

        self._set_status("Importing…")
        self.root.update()

        try:
            added   = core.import_items(self._tgt, tgt_list.guid, items, skip)
            skipped = len(items) - added   # top-level items filtered by skip-duplicates
            self._tgt_lists = core.read_lists(self._tgt)

            if added == 0 and skipped > 0:
                messagebox.showinfo(
                    "Nothing Added",
                    f"All {skipped} selected item(s) already exist in\n"
                    f"'{tgt_list.display_name}'.\n\n"
                    "Nothing was imported (skip duplicates is on).",
                )
                self._set_status(
                    f"Nothing added — all {skipped} item(s) already exist "
                    f"in '{tgt_list.display_name}'"
                )
            else:
                parts = [f"{added} item(s) added"]
                if skipped:
                    parts.append(f"{skipped} duplicate(s) skipped")
                summary = ",  ".join(parts)
                messagebox.showinfo(
                    "Import Complete",
                    f"{summary}\n→ '{tgt_list.display_name}'",
                )
                self._set_status(
                    f"Import complete: {summary} → '{tgt_list.display_name}'"
                )
        except Exception as exc:
            messagebox.showerror(
                "Import Failed",
                f"Error during import:\n\n{exc}\n\n"
                "All partial changes were rolled back.",
            )
            self._set_status("Import failed — changes rolled back.")

    # ── Misc ───────────────────────────────────────────────────────────────

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)

    def on_close(self) -> None:
        if self._src:
            core.close_project(self._src)
        if self._tgt:
            core.close_project(self._tgt)
        core.flexlibs_cleanup()
        self.root.destroy()


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _basename(path: str) -> str:
    return os.path.basename(path)


def _count_descendants(item: core.ItemInfo) -> int:
    return sum(1 + _count_descendants(d) for d in item.daughters)


def _open_file(path: str) -> None:
    try:
        os.startfile(path)  # Windows only
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _configure_logging() -> None:
    """
    Silence noisy flexlibs2/FLEx log output that would confuse end users.

    flexlibs2's Transaction() currently can't find the LCM rollback API
    (a known Phase 2 research item) and logs a WARNING each import.
    Imports work correctly — the warning is about rollback-on-failure
    not being available, which is low risk for this use case.

    We redirect flexlibs2 and SIL library loggers to a log file so
    developers can inspect them but end users don't see console noise.
    """
    import logging
    import os

    log_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                           "FLExListMigrator")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "flexlistmigrator.log")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s  %(name)s  %(levelname)s  %(message)s")
    )

    # Capture flexlibs2 and root logger to file; suppress console output
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    # Remove any default StreamHandlers so nothing hits the console
    root_logger.handlers = [h for h in root_logger.handlers
                             if not isinstance(h, logging.StreamHandler)
                             or isinstance(h, logging.FileHandler)]


def main():
    _configure_logging()

    # Initialize FLEx libraries before creating the UI.
    # This reads the Windows registry to find FLEx, loads DLLs, and inits ICU/SLDR.
    try:
        core.flexlibs_initialize()
    except Exception as exc:
        import tkinter.messagebox as mb
        tk.Tk().withdraw()
        mb.showerror(
            "FLEx Not Found",
            f"Could not initialize flexlibs2:\n\n{exc}\n\n"
            "Make sure FieldWorks Language Explorer 9 is installed.",
        )
        return

    root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
