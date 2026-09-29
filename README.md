# FLEx List Migrator

A standalone Windows app for migrating possibility list items between
[FieldWorks Language Explorer](https://software.sil.org/fieldworks/) (FLEx 9) projects.

## What it does

FLEx stores linguistic data in named lists — Parts of Speech, Semantic Domains,
Text Markup Tags, custom lists, and more. This tool lets you:

- **Browse** any list in a source FLEx project and check the items you want to move
- **Export** selected items to a portable JSON file — shareable with other users who have this tool
- **Load** a saved JSON file as a source and re-export or import from it just like a live project
- **Import** items into a matching list in a target FLEx project. The list is matched automatically by GUID, then by the field that owns it (for built-in lists), then by name (for custom lists).
- **Export human-readable** HTML or plain-text dumps of any list or selection for documentation or review

This version exports and imports **Text Chart Markers, Text Markup Tags and Text
Constituent Chart Templates**. You can browse other lists, but not export or
import them yet (see [Known issues](#known-issues)).

Each item carries every field FLEx shows for list items: Name, Abbreviation,
Description (including embedded writing systems and styles), Discussion,
Status, Confidence, Researchers, Restrictions and subitems. Transfer files are
checked when they are loaded, and each import is checked against the target
project before anything is written. See [TRANSFER_FORMAT.md](TRANSFER_FORMAT.md)
for the file format, which you can also write by hand. The `docs/examples/`
folder has a ready-made branch for the Text Chart Markers list.

All writes are wrapped in a transaction. FLEx must be closed while the tool runs.

## Known issues

- **Only three lists can be exported and imported.** Since 1.1.0, Save
  Transfer JSON, Export Human-Readable and Import Items work only for Text Chart
  Markers, Text Markup Tags and Text Constituent Chart Templates. Other lists
  are shown greyed out as "not supported yet". There are two reasons:
  - Some lists hold kinds of item the importer can't create yet: Complex Form
    Types and Variant Types (`LexEntryType`, `LexEntryInflType`), Lexical
    Relations (`LexRefType`) and Annotation Definitions (`CmAnnotationDefn`).
    Version 1.0.x imported these as plain list items of the wrong kind.
  - Other lists have fields specific to their items that aren't transferred,
    such as a Part of Speech's inflection features or a Semantic Domain's
    questions.

  Support may come in a future release. See
  [issue #1](https://github.com/rulingAnts/flex-list-migrator/issues/1).

## Requirements

- Windows (FLEx is Windows-only)
- [FieldWorks Language Explorer 9](https://software.sil.org/fieldworks/) installed
- [flexlibs2](https://github.com/cdfarrow/flexlibs) — install from the repo:
  ```
  pip install ./flexlibs2
  ```

## Running from source

```
pip install ./flexlibs2
python flex_list_migrator.py
```

## Building a standalone .exe

```
pip install ./flexlibs2 pyinstaller
pyinstaller build.spec
```

Output: `dist\FLExListMigrator.exe`

The .exe requires FLEx 9 to be installed on the target machine.
It does **not** require FLExTools or flexlibs2 to be separately installed —
those are bundled by PyInstaller.

## FLExTools testing module

`flex_module.py` is a [FLExTools](https://software.sil.org/flextools/) module that
validates the read and write paths against a live FLEx project.
Copy it (and `flex_core.py`) into your FLExTools Modules folder and run it in
**Modify mode** to test.

## File overview

| File | Purpose |
|---|---|
| `flex_list_migrator.py` | Main Tkinter GUI application |
| `flex_core.py` | FLEx project access, list reading/writing, JSON transfer format |
| `pretty_export.py` | HTML and plain-text human-readable export |
| `flex_module.py` | FLExTools module for development testing |
| `TRANSFER_FORMAT.md` | The transfer JSON format, its versions and validation |
| `docs/examples/` | Ready-made transfer files (e.g. an Evidentials branch for Text Chart Markers), also downloadable from the website |
| `build.spec` | PyInstaller build configuration |
| `requirements.txt` | Dependency notes |

## License

AGPL-3.0 — see [LICENSE](LICENSE).

## Credits

Developed by Seth Johnston with [Claude](https://claude.ai) (Anthropic).
FLEx LCM access via [flexlibs2](https://github.com/cdfarrow/flexlibs) by Craig Farrow.
