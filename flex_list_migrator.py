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

import glob
import os
import sys
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
        selected_fn,        # callable() -> [(ListInfo, checked items), ...]
    ):
        self.result: Optional[Tuple] = None  # (path, fmt, selections, ws, title)
        self._all_lists = all_lists
        self._current_list = current_list
        self._selected_fn = selected_fn

        win = tk.Toplevel(parent)
        win.title("Export Human-Readable")
        win.resizable(False, False)
        win.grab_set()
        self.window = win
        pad = {"padx": 8, "pady": 4}

        # Document title (used for the HTML <h1> heading and <title>)
        title_row = ttk.Frame(win)
        title_row.pack(fill="x", **pad)
        ttk.Label(title_row, text="Document title:").pack(side="left")
        default_title = current_list.display_name if current_list else ""
        self._title = tk.StringVar(value=default_title)
        ttk.Entry(title_row, textvariable=self._title).pack(
            side="left", fill="x", expand=True, padx=4)

        # Scope
        scope_f = ttk.LabelFrame(win, text="What to export")
        scope_f.pack(fill="x", **pad)
        self._scope = tk.StringVar(value="selected")
        ttk.Radiobutton(
            scope_f, text="Checked items only (in all lists)",
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

        if scope == "selected":
            selections = self._selected_fn()
        else:
            for var, li in self._list_vars:
                if var.get():
                    selections.append((li, li.items))

        if not selections:
            messagebox.showwarning("Nothing to export",
                                   "No items selected for export.",
                                   parent=self.window)
            return

        title = self._title.get().strip()
        self.result = (path, fmt, selections, ws, title)
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
        # The app opens with Template selected (FLEx Project if none are bundled).
        self._source_type_var = tk.StringVar(value="template")
        self._src_json_path_var = tk.StringVar()
        self._src_json_label: str = ""   # display label when JSON is source
        self._list_prefix = ""            # e.g. "[JSON]  " before each list's name
        self._list_origin: Dict[int, str] = {}   # id(list) -> file it came from

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
        ttk.Radiobutton(radio_row, text="Template",
                        variable=self._source_type_var, value="template",
                        command=self._on_source_type_change).pack(side="left", padx=(12, 0))

        # FLEx input row
        self._flex_src_row = ttk.Frame(src_frame)
        ttk.Label(self._flex_src_row, text="Project:").pack(side="left")
        self._src_combo = ttk.Combobox(self._flex_src_row, width=36, state="normal")
        self._src_combo.pack(side="left", padx=4)
        ttk.Button(self._flex_src_row, text="Browse folder…",
                   command=self._browse_folder).pack(side="left")
        ttk.Button(self._flex_src_row, text="Load",
                   command=self._load_source).pack(side="left", padx=(6, 0))

        # JSON input row
        self._json_src_row = ttk.Frame(src_frame)
        ttk.Label(self._json_src_row, text="File:").pack(side="left")
        ttk.Entry(self._json_src_row, textvariable=self._src_json_path_var,
                  width=44).pack(side="left", padx=4, fill="x", expand=True)
        ttk.Button(self._json_src_row, text="Browse…",
                   command=self._browse_source_json).pack(side="left")
        ttk.Button(self._json_src_row, text="Load",
                   command=self._load_source).pack(side="left", padx=(6, 0))

        # Template input row: lists bundled with the app, shown by their
        # description.
        self._tpl_src_row = ttk.Frame(src_frame)
        ttk.Label(self._tpl_src_row, text="Template:").pack(side="left")
        self._tpl_combo = ttk.Combobox(self._tpl_src_row, width=60, state="readonly")
        self._tpl_combo.pack(side="left", padx=4, fill="x", expand=True)
        ttk.Button(self._tpl_src_row, text="Load",
                   command=self._load_source).pack(side="left", padx=(6, 0))
        ttk.Button(self._tpl_src_row, text="Submit yours…",
                   command=_open_template_submission).pack(side="left", padx=(6, 0))
        self._templates = _find_templates()
        self._tpl_combo["values"] = [desc for desc, _path in self._templates]
        if self._templates:
            self._tpl_combo.current(0)
        else:
            self._tpl_combo.set("No templates are included in this copy of the app")
            self._source_type_var.set("flex")   # open on FLEx Project instead
        self._show_source_row()

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
        # Shown above the tree when the selected list can't be exported/imported.
        self._support_note = ttk.Label(item_f, foreground="#a15c00",
                                       wraplength=620, justify="left")
        self._support_anchor = ty
        ty.pack(side="right", fill="y")
        tx.pack(side="bottom", fill="x")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<Button-1>", self._on_item_click)
        self._tree.tag_configure("checked", foreground="#000")
        self._tree.tag_configure("unchecked", foreground="#888")

        btn_row = ttk.Frame(item_f)
        btn_row.pack(fill="x", pady=(4, 0))
        select_btn = ttk.Menubutton(btn_row, text="Select All")
        select_menu = tk.Menu(select_btn, tearoff=False)
        select_menu.add_command(label="In this list", command=self._select_all_in_list)
        select_menu.add_command(label="In all supported lists",
                                command=self._select_all_lists)
        select_btn["menu"] = select_menu
        select_btn.pack(side="left", padx=2)
        ttk.Button(btn_row, text="Deselect All",
                   command=self._deselect_all).pack(side="left", padx=2)
        for label, cmd in (
            ("Expand All",    lambda: self._expand_all(True)),
            ("Collapse All",  lambda: self._expand_all(False)),
        ):
            ttk.Button(btn_row, text=label, command=cmd).pack(side="left", padx=2)

        # Export buttons
        exp_row = ttk.Frame(self.root)
        exp_row.pack(fill="x", padx=6, pady=2)
        self._save_btn = ttk.Button(exp_row, text="Save Transfer JSON…",
                                    command=self._save_json)
        self._save_btn.pack(side="left")
        self._export_btn = ttk.Button(exp_row, text="Export Human-Readable…",
                                      command=self._export_readable)
        self._export_btn.pack(side="left", padx=8)

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

        self._import_btn = ttk.Button(tgt_frame, text="⬇  Import Items",
                                      command=self._do_import)
        self._import_btn.pack(anchor="w", pady=(2, 0))

        # Status bar
        self._status_var = tk.StringVar(
            value="Ready. Choose a template, JSON file or FLEx project, then click Load.")
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
        self._show_source_row()
        # Clear whatever was loaded as the previous source type
        self._clear_source()

    def _show_source_row(self):
        """Show the input row for the selected source type and hide the others."""
        rows = {"flex": self._flex_src_row, "json": self._json_src_row,
                "template": self._tpl_src_row}
        for row in rows.values():
            row.pack_forget()
        rows[self._source_type_var.get()].pack(fill="x")

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
        self._list_origin = {}
        self._list_box.delete(0, "end")
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        self._update_support_ui()

    def _browse_source_json(self):
        paths = filedialog.askopenfilenames(
            title="Select Transfer JSON (one or more files)",
            filetypes=[("JSON", "*.json"), ("All Files", "*.*")],
        )
        if paths:
            self._src_json_path_var.set("; ".join(paths))

    def _load_source(self):
        kind = self._source_type_var.get()
        if kind == "json":
            self._load_source_json()
        elif kind == "template":
            self._load_template()
        else:
            self._load_source_flex()

    def _load_template(self):
        i = self._tpl_combo.current()
        if not 0 <= i < len(self._templates):
            messagebox.showwarning("No Template", "Choose a template first.")
            return
        self.load_json_files([self._templates[i][1]], kind="Template")

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
            self._checked.clear()
            self._list_origin = {}
            self._refresh_list_box()
            n_ok = sum(1 for li in self._src_lists if not core.unsupported_reason(li))
            self._set_status(
                f"Source: {name}  ({len(self._src_lists)} lists; "
                f"{n_ok} can be exported and imported in this version)"
            )
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))
            self._set_status("Source project failed to load.")

    def _load_source_json(self):
        paths = [p.strip() for p in self._src_json_path_var.get().split(";") if p.strip()]
        self.load_json_files(paths)

    def open_files(self, paths: List[str]) -> None:
        """Open transfer files as the source (used for files given at startup)."""
        if self._source_type_var.get() != "json":
            self._source_type_var.set("json")
            self._on_source_type_change()
        self.load_json_files(paths)

    def load_json_files(self, paths: List[str], kind: str = "JSON") -> bool:
        """Load one or more transfer files as the source.

        kind ("JSON" or "Template") labels the lists and the status line.
        All or nothing: if any file can't be loaded, none are.
        """
        if not paths:
            messagebox.showwarning("No File", "Browse to a transfer JSON file first.")
            return False
        missing = [p for p in paths if not os.path.isfile(p)]
        if missing:
            messagebox.showwarning("File Not Found", "Can't find:\n" + "\n".join(missing))
            return False
        loaded = []   # (path, metadata, lists, notes)
        for path in paths:
            try:
                meta, lists, notes = core.load_from_json(path)
            except Exception as exc:
                messagebox.showerror("Can't Load JSON", f"{_basename(path)}:\n\n{exc}")
                return False
            loaded.append((path, meta, lists, notes))
        several = len(loaded) > 1
        notes = [f"{_basename(p)}: {n}" if several else n
                 for p, _meta, _lists, file_notes in loaded for n in file_notes]
        if notes:
            messagebox.showwarning("Loaded with notes",
                                   _bullets("Loaded, with these notes:", notes, 10).strip())

        # With several files, each list is labelled with the file it came from.
        self._list_origin = {}
        all_lists: List[core.ListInfo] = []
        for path, _meta, lists, _notes in loaded:
            for li in lists:
                # A list with no name or known type (e.g. a hand-made file) is
                # shown by the file's name.
                if not li.name.vals and not li.owner:
                    li.name = core.MultiStr({"en": _basename(path)})
                if several:
                    self._list_origin[id(li)] = _basename(path)
                all_lists.append(li)
        projects = sorted({m.get("source_project", "") for _p, m, _l, _n in loaded} - {""})
        self._src_json_label = ", ".join(projects)
        if kind == "JSON":
            self._src_json_path_var.set("; ".join(paths))
        self._src_lists = all_lists
        self._checked.clear()
        self._refresh_list_box(prefix=f"[{kind}]  ")
        # Select the first list so the tree populates immediately
        self._list_box.selection_set(0)
        self._on_list_select()
        n_total = sum(_count_items(li.items) for li in all_lists)
        versions = "/".join(f"v{v}" for v in sorted({m["format_version"] for _p, m, _l, _n in loaded}))
        self._set_status(
            (f"{kind} source: {len(loaded)} files, " if several else f"{kind} source: ")
            + f"{len(all_lists)} list{'s' if len(all_lists) != 1 else ''}, {n_total} items"
            + (f"  from '{self._src_json_label}'" if self._src_json_label else "")
            + f"  [format {versions}]"
        )
        return True

    def _list_label(self, li: core.ListInfo) -> str:
        origin = self._list_origin.get(id(li))
        label = (f"[{origin}]  " if origin else self._list_prefix) + li.display_name
        if core.unsupported_reason(li):
            return f"{label}   (not supported yet)"
        n = _count_items(self._filter_checked(li.items))
        return f"{label}   ({n} checked)" if n else label

    def _refresh_list_box(self, prefix: str = ""):
        self._list_prefix = prefix
        # Lists this version can export/import first; the rest greyed out.
        self._src_lists.sort(key=lambda li: core.unsupported_reason(li) is not None)
        self._list_box.delete(0, "end")
        for i, li in enumerate(self._src_lists):
            self._list_box.insert("end", self._list_label(li))
            if core.unsupported_reason(li):
                self._list_box.itemconfig(i, foreground="#999999")

    def _update_list_label(self) -> None:
        """Refresh the selected list's label after its checks change."""
        if self._current_list is None:
            return
        i = self._src_lists.index(self._current_list)
        self._list_box.delete(i)
        self._list_box.insert(i, self._list_label(self._current_list))
        self._list_box.selection_set(i)

    def _on_list_select(self, _event=None):
        sel = self._list_box.curselection()
        if not sel or not self._src_lists:
            return
        li = self._src_lists[sel[0]]
        self._current_list = li
        # Checked items are kept per item across lists; only the tree is rebuilt.
        self._iid_to_guid.clear()
        self._guid_to_name.clear()
        self._guid_to_item.clear()
        self._populate_tree(li)
        reason = self._update_support_ui()
        self._set_status(f"{li.display_name}  —  {len(li.items)} top-level item(s)"
                         + ("  (not supported yet: browse only)" if reason else "")
                         + self._selection_summary())

    def _update_support_ui(self) -> Optional[str]:
        """Show or hide the not-supported note for the selected list.
        Returns the reason it isn't supported, if any."""
        reason = core.unsupported_reason(self._current_list) if self._current_list else None
        if reason:
            self._support_note.configure(
                text=reason + " You can browse it here, but not check, export or "
                "import its items.")
            self._support_note.pack(side="top", fill="x", pady=(0, 4),
                                    before=self._support_anchor)
        else:
            self._support_note.pack_forget()
        return reason

    def _browse_only(self) -> bool:
        """True (with a status note) if the selected list's items can't be checked."""
        if self._current_list is not None and core.unsupported_reason(self._current_list):
            self._set_status(f"{self._current_list.display_name} is not supported yet: "
                             "its items can't be checked.")
            return True
        return False

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
        if not guid or self._browse_only():
            return
        if guid in self._checked:
            self._uncheck(iid)
        else:
            self._check(iid)
        self._after_check_change()

    def _after_check_change(self) -> None:
        self._update_list_label()
        self._set_status(self._selection_summary().strip(" ·") or "Nothing checked")

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

    def _select_all_in_list(self) -> None:
        """Check every item in the selected list; other lists keep their checks."""
        if self._current_list is None or self._browse_only():
            return
        for iid in self._tree.get_children():
            self._check(iid)
        self._after_check_change()

    def _select_all_lists(self) -> None:
        """Check every item in every supported list."""
        supported = [li for li in self._src_lists if not core.unsupported_reason(li)]
        if not supported:
            self._set_status("None of these lists can be exported or imported yet.")
            return

        def add(items: List[core.ItemInfo]) -> None:
            for item in items:
                self._checked.add(item.original_guid)
                add(item.daughters)

        for li in supported:
            add(li.items)
        if self._current_list in supported:
            for iid in self._tree.get_children():
                self._check(iid)          # show the ticks in the open list
        self._refresh_list_labels()
        self._set_status(self._selection_summary().strip(" ·"))

    def _deselect_all(self) -> None:
        """Uncheck every item in every list, after confirming."""
        if not self._checked:
            self._set_status("Nothing is checked.")
            return
        n_lists = sum(1 for li in self._src_lists if self._has_checks(li.items))
        if not messagebox.askyesno(
                "Deselect All",
                f"Uncheck all {len(self._checked)} checked item(s) in {n_lists} "
                f"list{'s' if n_lists != 1 else ''}?"):
            return
        self._checked.clear()
        for iid in self._tree.get_children():
            self._uncheck(iid)
        self._refresh_list_labels()
        self._set_status("Nothing checked")

    def _has_checks(self, items: List[core.ItemInfo]) -> bool:
        return any(i.original_guid in self._checked or self._has_checks(i.daughters)
                   for i in items)

    def _refresh_list_labels(self) -> None:
        """Update every list's label (checked counts), keeping the selection."""
        for i, li in enumerate(self._src_lists):
            self._list_box.delete(i)
            self._list_box.insert(i, self._list_label(li))
            if core.unsupported_reason(li):
                self._list_box.itemconfig(i, foreground="#999999")
        if self._current_list is not None:
            self._list_box.selection_set(self._src_lists.index(self._current_list))

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

    def _selections(self) -> List[Tuple[core.ListInfo, List[core.ItemInfo]]]:
        """Checked items of every supported list, as [(list, items), ...].

        This is what Save, Import and the readable export use.  An item counts
        only if the items above it are checked too.
        """
        result = []
        for li in self._src_lists:
            if core.unsupported_reason(li):
                continue
            items = self._filter_checked(li.items)
            if items:
                result.append((li, items))
        return result

    def _selection_summary(self) -> str:
        sel = self._selections()
        if not sel:
            return ""
        n = sum(_count_items(items) for _, items in sel)
        return (f"  ·  {n} item{'s' if n != 1 else ''} checked in "
                f"{len(sel)} list{'s' if len(sel) != 1 else ''}")

    def _filter_checked(self, items: List[core.ItemInfo]) -> List[core.ItemInfo]:
        return [
            item.copy(daughters=self._filter_checked(item.daughters))
            for item in items
            if item.original_guid in self._checked
        ]

    # ── JSON export ────────────────────────────────────────────────────────

    def _save_json(self):
        selections = self._selections()
        if not selections:
            messagebox.showwarning("Nothing Selected",
                                   "Check items in one or more lists, then save.")
            return
        path = filedialog.asksaveasfilename(
            title="Save Transfer JSON",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            if self._source_type_var.get() in ("json", "template"):
                src_name = self._src_json_label or _basename(self._src_json_path_var.get())
            else:
                src_name = self._src_combo.get().strip()
            version = core.save_transfer(selections, src_name, path)
            n = sum(_count_items(items) for _, items in selections)
            self._set_status(
                f"Saved {n} item(s) from {len(selections)} list(s) → {_basename(path)}"
                + ("  (a multi-list file: FLEx List Migrator 1.2 or later can open it)"
                   if version >= 3 else ""))
        except Exception as exc:
            messagebox.showerror("Save Error", str(exc))

    # ── Human-readable export ──────────────────────────────────────────────

    def _export_readable(self):
        if not self._src_lists:
            messagebox.showwarning("No Source",
                                   "Load a source project or JSON file first.")
            return
        exportable = [li for li in self._src_lists if not core.unsupported_reason(li)]
        if not exportable:
            messagebox.showwarning("Not Supported Yet",
                                   "None of these lists can be exported yet. "
                                   + core.NOT_SUPPORTED_YET)
            return
        current = self._current_list if self._current_list in exportable else None
        dlg = ExportReadableDialog(self.root, exportable, current, self._selections)
        self.root.wait_window(dlg.window)
        if not dlg.result:
            return
        path, fmt, selections, ws, title = dlg.result
        try:
            if fmt == "html":
                pretty_export.export_html(selections, path, preferred_ws=ws,
                                          title=title)
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

    _MATCH_NOTES = {
        "guid": "matched by GUID",
        "owner": "matched by list type",
        "name": "matched by name — check this is right",
        "manual": "chosen by you",
    }

    def _do_import(self):
        selections = self._selections()
        if not selections:
            messagebox.showwarning("Nothing to Import",
                                   "Check items in one or more lists first.")
            return
        if not self._tgt:
            messagebox.showwarning("No Target", "Load a target project first.")
            return

        # Only lists this version supports can receive items.
        targets = [li for li in self._tgt_lists if core.is_supported_list(li)]
        if not targets:
            messagebox.showwarning(
                "No Supported List",
                "The target project has none of the lists this version can import "
                "into. " + core.NOT_SUPPORTED_YET)
            return

        # Find the target list for each source list with checked items.
        plan = []   # (source list, items, target list, how it was matched)
        for src_li, items in selections:
            tgt_li, how = core.find_matching_list(targets, src_li)
            if how == "none":
                dlg = _ListPickerDialog(self.root, targets, src_li.display_name)
                self.root.wait_window(dlg.window)
                if not dlg.result:
                    return
                tgt_li, how = dlg.result, "manual"
            plan.append((src_li, items, tgt_li, how))

        skip = self._skip_var.get()

        # Check the import against the target before anything is written.
        notes: List[str] = []
        try:
            for _src_li, items, tgt_li, _how in plan:
                for note in core.preflight_import(self._tgt, tgt_li.guid, items, skip):
                    notes.append(f"{tgt_li.display_name}: {note}" if len(plan) > 1 else note)
        except Exception as exc:
            messagebox.showerror("Can't Import", f"The import check failed:\n\n{exc}")
            return

        lines = [f"• {_count_items(items)} item(s) from '{src_li.display_name}'\n"
                 f"    into '{tgt_li.display_name}' ({self._MATCH_NOTES[how]})"
                 for src_li, items, tgt_li, how in plan]
        confirmed = messagebox.askyesno(
            "Confirm Import",
            "Import:\n" + "\n".join(lines) + "\n\n"
            f"Skip duplicates: {'yes' if skip else 'no'}\n\n"
            + _bullets("Check before importing:", notes, 8)
            + "Shared project? Do a Send/Receive in FLEx before importing.\n"
            "FLEx must stay closed until this completes.",
        )
        if not confirmed:
            return

        self._set_status("Importing…")
        self.root.update()

        try:
            warnings: List[str] = []
            added = core.import_selections(
                self._tgt, [(tgt_li.guid, items) for _s, items, tgt_li, _h in plan],
                skip, warnings=warnings)
            self._tgt_lists = core.read_lists(self._tgt)
        except Exception as exc:
            messagebox.showerror(
                "Import Failed",
                f"Error during import:\n\n{exc}\n\n"
                "All partial changes were rolled back.",
            )
            self._set_status("Import failed — changes rolled back.")
            return

        results = []
        for (_src_li, items, tgt_li, _how), n_added in zip(plan, added):
            n_skipped = len(items) - n_added   # top-level items that were already there
            results.append(f"'{tgt_li.display_name}': {n_added} top-level item(s) added"
                           + (f", {n_skipped} already there (skipped)" if n_skipped else ""))
        total = sum(added)
        messagebox.showinfo(
            "Import Complete" if total else "Nothing Added",
            "\n".join(results) + "\n\n"
            + _bullets("Imported with these notes:", warnings, 8)
            + ("The import is saved to the project when you close FLEx List Migrator "
               "(or load another target project). Then open the project in FLEx, "
               "and Send/Receive if it's shared." if total else
               "Nothing was imported (Skip duplicates is on)."),
        )
        self._set_status(
            f"Import complete: {total} top-level item(s) added to {len(plan)} list(s)"
            + (f"  ({len(warnings)} note(s))" if warnings else ""))

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


def _count_items(items: List[core.ItemInfo]) -> int:
    """Items plus all their subitems."""
    return sum(1 + _count_descendants(i) for i in items)


def _bullets(title: str, lines: List[str], limit: int) -> str:
    """A titled bullet list for a message box, or '' if there are no lines."""
    if not lines:
        return ""
    shown = lines[:limit]
    more = len(lines) - len(shown)
    return (title + "\n• " + "\n• ".join(shown)
            + (f"\n• …and {more} more" if more else "") + "\n\n")


def _count_descendants(item: core.ItemInfo) -> int:
    return sum(1 + _count_descendants(d) for d in item.daughters)


def _set_window_icon(root: tk.Tk) -> None:
    """Show the app icon on this and every later window instead of Tk's feather.

    Frozen (.exe) builds unpack bundled files to sys._MEIPASS (see build.spec).
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    try:
        root.iconbitmap(default=os.path.join(base, "app_icon.ico"))
    except tk.TclError:
        pass


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


USAGE = """Usage:  FLEx List Migrator [--no-preload] [FILE.json ...]

FILE.json      Transfer files to open as the source. Dropping files onto
               the app's icon opens them the same way.
--no-preload   Don't open the lists in a "preload" folder.

With no files named, the app opens any .json files in a "preload" folder,
either built into the app or next to it."""


TEMPLATE_SUBMISSION_URL = ("https://github.com/rulingAnts/flex-list-migrator/issues/new"
                           "?template=template-submission.yml")


def _find_templates() -> List[Tuple[str, str]]:
    """Bundled templates as [(description, path)], sorted by description.

    Templates are transfer files in a "templates" folder: built into the .exe
    (see build.spec), in the source folder, or next to the app.  Each is
    listed by its "description", or by its lists' names if it has none; files
    that don't load are left out.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else here
    dirs = [os.path.join(getattr(sys, "_MEIPASS", here), "templates"),
            os.path.join(app_dir, "templates")]
    found: Dict[str, Tuple[str, str]] = {}
    for folder in dict.fromkeys(dirs):            # each folder once, in order
        for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
            name = os.path.basename(path)
            if name in found:
                continue
            try:
                meta, lists, _notes = core.load_from_json(path)
            except Exception:
                continue
            desc = (meta.get("description") or "").strip() \
                or ", ".join(li.display_name for li in lists) or name
            found[name] = (desc, path)
    return sorted(found.values(), key=lambda t: t[0].lower())


def _open_template_submission() -> None:
    """Open the GitHub form for suggesting a template, in the default browser."""
    import webbrowser
    webbrowser.open(TEMPLATE_SUBMISSION_URL)


def _startup_files(args: List[str]) -> List[str]:
    """Transfer files to open when the app starts.

    Files named on the command line win (dropping files onto the .exe names
    them).  Otherwise the .json files in a "preload" folder are used: one built
    into the .exe (see build.spec) or one next to the app.
    """
    files = [os.path.abspath(a) for a in args if not a.startswith("-")]
    if files or "--no-preload" in args:
        return files
    for folder in _preload_dirs():
        found = sorted(glob.glob(os.path.join(folder, "*.json")))
        if found:
            return found
    return []


def _preload_dirs() -> List[str]:
    dirs = []
    if hasattr(sys, "_MEIPASS"):                     # built into the .exe
        dirs.append(os.path.join(sys._MEIPASS, "preload"))
    app_dir = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                              else os.path.abspath(__file__))
    dirs.append(os.path.join(app_dir, "preload"))   # next to the app
    return dirs


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
    _set_window_icon(root)
    if any(a in ("-h", "--help", "/?") for a in sys.argv[1:]):
        root.withdraw()
        messagebox.showinfo("FLEx List Migrator", USAGE)
        return
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    files = _startup_files(sys.argv[1:])
    if files:
        root.after(200, lambda: app.open_files(files))
    root.mainloop()


if __name__ == "__main__":
    main()
