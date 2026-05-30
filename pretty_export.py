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
<title>FLEx List Export</title>
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
  ul.root-list { list-style: none; padding-left: 0; }
  ul { list-style: disc; padding-left: 1.4em; }
  li { margin: .25em 0; }
  .item-name { font-weight: 500; }
  .item-abbr { color: #666; font-size: .88em; font-style: italic; }
  .item-desc { color: #666; font-size: .88em; margin: .1em 0 .1em 1em; }
</style>
</head>
<body>
<h1>FLEx List Export</h1>
"""

_HTML_FOOT = "</body>\n</html>\n"


def export_html(
    selections: List[Tuple[ListInfo, List[ItemInfo]]],
    out_path: str | Path,
    preferred_ws: str = "en",
) -> None:
    parts: List[str] = [_HTML_HEAD]

    for li, items in selections:
        name = _esc(li.name.best(preferred_ws) or li.guid)
        abbr = li.abbr.best(preferred_ws)
        desc = li.desc.best(preferred_ws) if hasattr(li, "desc") else ""
        abbr_span = f' <span class="list-abbr">({_esc(abbr)})</span>' if abbr else ""
        parts.append(f"<section>\n<h2>{name}{abbr_span}</h2>")
        if desc:
            parts.append(f'<p class="list-desc">{_esc(desc)}</p>')
        parts.append('<ul class="root-list">')
        for item in items:
            _html_item(item, parts, preferred_ws)
        parts.append("</ul>\n</section>")

    parts.append(_HTML_FOOT)
    Path(out_path).write_text("\n".join(parts), encoding="utf-8")


def _html_item(item: ItemInfo, parts: List[str], ws: str) -> None:
    name = _esc(item.name.best(ws) or "(unnamed)")
    abbr = item.abbr.best(ws)
    desc = item.desc.best(ws)
    abbr_span = f' <span class="item-abbr">({_esc(abbr)})</span>' if abbr else ""
    parts.append(f'<li><span class="item-name">{name}</span>{abbr_span}')
    if desc:
        parts.append(f'<p class="item-desc">{_esc(desc)}</p>')
    if item.daughters:
        parts.append("<ul>")
        for d in item.daughters:
            _html_item(d, parts, ws)
        parts.append("</ul>")
    parts.append("</li>")


def _esc(text: str) -> str:
    return html_lib.escape(text, quote=False)
