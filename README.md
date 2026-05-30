# FLEx List Migrator

A standalone Windows app for migrating possibility list items between
[FieldWorks Language Explorer](https://software.sil.org/fieldworks/) (FLEx 9) projects.

## What it does

FLEx stores linguistic data in named lists — Parts of Speech, Semantic Domains,
Text Markup Tags, custom lists, and more. This tool lets you:

- **Browse** any list in a source FLEx project and check the items you want to move
- **Export** selected items to a portable JSON file — shareable with other users who have this tool
- **Load** a saved JSON file as a source and re-export or import from it just like a live project
- **Import** items into a matching list in a target FLEx project, with automatic list matching by GUID (built-in lists) or name (custom lists)
- **Export human-readable** HTML or plain-text dumps of any list or selection for documentation or review

All writes are wrapped in a transaction. FLEx must be closed while the tool runs.

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
| `build.spec` | PyInstaller build configuration |
| `requirements.txt` | Dependency notes |

## License

AGPL-3.0 — see [LICENSE](LICENSE).

## Credits

Developed by Seth Johnston with [Claude](https://claude.ai) (Anthropic).
FLEx LCM access via [flexlibs2](https://github.com/cdfarrow/flexlibs) by Craig Farrow.
