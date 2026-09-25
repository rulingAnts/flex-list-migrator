"""
Human-readable export of FLEx list items.

Supports plain-text (indented) and HTML (styled) output.
Input: List of (ListInfo, List[ItemInfo]) tuples from flex_core.
"""

from __future__ import annotations

import html as html_lib
from pathlib import Path
from typing import List, Tuple

from flex_core import ItemInfo, ListInfo


# ---------------------------------------------------------------------------
# Plain text export
# ---------------------------------------------------------------------------

def export_text(
    selections: List[Tuple[ListInfo, List[ItemInfo]]],
    out_path: str | Path,
    preferred_ws: str = "en",
) -> None:
    lines: List[str] = []
    for li, items in selections:
        header = li.name.best(preferred_ws) or li.guid
        abbr = li.abbr.best(preferred_ws)
        if abbr:
            header = f"{header} ({abbr})"
        lines.append(header)
        lines.append("=" * len(header))
        for item in items:
            _text_item(item, lines, preferred_ws, depth=0)
        lines.append("")

    Path(out_path).write_text("\n".join(lines), encoding="utf-8")


def _text_item(item: ItemInfo, lines: List[str], ws: str, depth: int) -> None:
    indent = "  " * depth
    name = item.name.best(ws) or "(unnamed)"
    abbr = item.abbr.best(ws)
    desc = item.desc.best(ws)
    abbr_part = f" ({abbr})" if abbr else ""
    lines.append(f"{indent}• {name}{abbr_part}")
    if desc:
        lines.append(f"{indent}  {desc}")
    for d in item.daughters:
        _text_item(d, lines, ws, depth + 1)


# ---------------------------------------------------------------------------
# HTML export
# ---------------------------------------------------------------------------

_HTML_HEAD = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>__DOC_TITLE__</title>
<style>
  body {
    font-family: "Segoe UI", Calibri, Arial, sans-serif;
    max-width: 860px;
    margin: 2em auto;
    color: #1a1a1a;
    line-height: 1.5;
  }
  h1 { color: #2c5f8a; border-bottom: 3px solid #2c5f8a; padding-bottom: .3em; }
  h2 { color: #1a5fa8; border-bottom: 1px solid #90b8d8; padding-bottom: .2em; }
  .list-abbr { color: #555; font-style: italic; font-size: .9em; }
  .list-desc { color: #555; font-style: italic; margin: .2em 0 .8em 0; }
  .root-list { padding-left: 0; }
  .children {
    padding-left: 1.4em;
    margin-left: .4em;
    border-left: 1px solid #e0e0e0;
  }
  .item { margin: .25em 0; }
  /* Collapsible parents (native <details>); collapsed by default. */
  details > summary {
    cursor: pointer;
    list-style: none;            /* replace default marker with our own */
  }
  details > summary::-webkit-details-marker { display: none; }
  details > summary::before {
    content: "\\25B8";           /* ▸ */
    display: inline-block;
    width: 1em;
    color: #2c5f8a;
  }
  details[open] > summary::before { content: "\\25BE"; }  /* ▾ */
  /* Leaf items: bullet aligned with the disclosure triangle above. */
  .leaf::before {
    content: "\\2022";           /* • */
    display: inline-block;
    width: 1em;
    color: #888;
  }
  .item-name { font-weight: 500; }
  .item-abbr { color: #666; font-size: .88em; font-style: italic; }
  .item-desc { color: #666; font-size: .88em; margin: .1em 0 .1em 1.2em; }
  /* Tabs (JS-free, CSS radio technique) — used only for 2+ lists. */
  .tabs { margin-top: 1em; }
  .tab-radio { position: absolute; opacity: 0; pointer-events: none; }
  .tab-bar {
    display: flex; flex-wrap: wrap; gap: .3em;
    border-bottom: 2px solid #2c5f8a; margin-bottom: 1em;
  }
  .tab-bar label {
    cursor: pointer; padding: .4em .9em; margin-bottom: -2px;
    border: 1px solid #90b8d8; border-bottom: none; border-radius: 6px 6px 0 0;
    background: #eef4fa; color: #1a5fa8; font-weight: 500;
  }
  .tab-bar label:hover { background: #dce9f6; }
  .tab-panel { display: none; }
  .tab-panel > h2 { margin-top: 0; }
</style>
</head>
<body>
<h1>__DOC_TITLE__</h1>
"""

DEFAULT_TITLE = "FLEx List Export"

_HTML_FOOT = "</body>\n</html>\n"


def export_html(
    selections: List[Tuple[ListInfo, List[ItemInfo]]],
    out_path: str | Path,
    preferred_ws: str = "en",
    title: str = DEFAULT_TITLE,
) -> None:
    doc_title = (title or "").strip() or DEFAULT_TITLE
    parts: List[str] = [_HTML_HEAD.replace("__DOC_TITLE__", _esc(doc_title))]

    if len(selections) > 1:
        # Multiple lists -> put each on its own tab (CSS radio technique).
        # Per-tab mapping rules are generated here since the count is dynamic.
        rules: List[str] = []
        for i in range(len(selections)):
            rules.append(
                f'#flt-{i}:checked ~ .tab-bar label[for="flt-{i}"]'
                " { background: #2c5f8a; color: #fff; border-color: #2c5f8a; }"
            )
            rules.append(f"#flt-{i}:checked ~ #flp-{i} {{ display: block; }}")
        parts.append("<style>\n" + "\n".join(rules) + "\n</style>")

        parts.append('<div class="tabs">')
        for i in range(len(selections)):
            checked = " checked" if i == 0 else ""
            parts.append(
                f'<input class="tab-radio" type="radio" name="flt" id="flt-{i}"{checked}>'
            )
        parts.append('<nav class="tab-bar">')
        for i, (li, _items) in enumerate(selections):
            tab_name = _esc(li.name.best(preferred_ws) or li.guid)
            parts.append(f'<label for="flt-{i}">{tab_name}</label>')
        parts.append("</nav>")
        for i, (li, items) in enumerate(selections):
            parts.append(f'<section class="tab-panel" id="flp-{i}">')
            _html_list_body(li, items, parts, preferred_ws)
            parts.append("</section>")
        parts.append("</div>")
    else:
        for li, items in selections:
            parts.append("<section>")
            _html_list_body(li, items, parts, preferred_ws)
            parts.append("</section>")

    parts.append(_HTML_FOOT)
    Path(out_path).write_text("\n".join(parts), encoding="utf-8")


def _html_list_body(li: ListInfo, items: List[ItemInfo], parts: List[str], ws: str) -> None:
    """Render one list's heading, description, and item tree into ``parts``."""
    name = _esc(li.name.best(ws) or li.guid)
    abbr = li.abbr.best(ws)
    desc = li.desc.best(ws) if hasattr(li, "desc") else ""
    abbr_span = f' <span class="list-abbr">({_esc(abbr)})</span>' if abbr else ""
    parts.append(f"<h2>{name}{abbr_span}</h2>")
    if desc:
        parts.append(f'<p class="list-desc">{_esc(desc)}</p>')
    parts.append('<div class="root-list">')
    for item in items:
        _html_item(item, parts, ws)
    parts.append("</div>")


def _html_item(item: ItemInfo, parts: List[str], ws: str) -> None:
    name = _esc(item.name.best(ws) or "(unnamed)")
    abbr = item.abbr.best(ws)
    desc = item.desc.best(ws)
    abbr_span = f' <span class="item-abbr">({_esc(abbr)})</span>' if abbr else ""
    label = f'<span class="item-name">{name}</span>{abbr_span}'
    desc_p = f'<p class="item-desc">{_esc(desc)}</p>' if desc else ""

    if item.daughters:
        # Collapsible parent — <details> is collapsed by default (no `open`).
        parts.append('<div class="item">')
        parts.append(f"<details><summary>{label}</summary>")
        if desc_p:
            parts.append(desc_p)
        parts.append('<div class="children">')
        for d in item.daughters:
            _html_item(d, parts, ws)
        parts.append("</div>")  # .children
        parts.append("</details>")
        parts.append("</div>")  # .item
    else:
        # Leaf item — no disclosure control.
        parts.append(f'<div class="item leaf">{label}')
        if desc_p:
            parts.append(desc_p)
        parts.append("</div>")


def _esc(text: str) -> str:
    return html_lib.escape(text, quote=False)
