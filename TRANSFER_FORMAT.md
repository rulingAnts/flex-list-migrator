# Transfer JSON format

**Save Transfer JSON…** writes the checked items, from one list or several,
to a UTF-8 JSON file, and **Source → JSON File** reads one back. You can also
write these files by hand, for example to add a ready-made branch to a list.
See
[`docs/examples/evidentials-text-chart-markers.json`](docs/examples/evidentials-text-chart-markers.json).

## Version statement

Every file begins by saying what it is and which version of the format it uses:

```json
{
  "format": "flex-list-migrator",
  "format_version": 3,
  ...
}
```

| Version | Holds | Written by | Read by |
|---|---|---|---|
| 1 (`"format": "flex-list-migrator-v1"`) | one list | 1.0.x | every version |
| 2 | one list | 1.1, and 1.2 or later for a single list | 1.1 and later |
| 3 | one or more lists | 1.2 and later, when saving several lists | 1.2 and later |

Newer versions keep reading older files, and a file with one list is still
written as version 2 so that 1.1 can open it. A file with a *newer* version than
the app understands is refused, with a message to update the app.

## Which lists

This version exports and imports only **Text Chart Markers**, **Text Markup
Tags** and **Text Constituent Chart Templates**. Their items are all plain
`CmPossibility` objects. A file for any other list, or with items of another
class, still loads so you can look at it, but it can't be imported or
re-exported. See
[issue #1](https://github.com/rulingAnts/flex-list-migrator/issues/1).

## Validation

A file is checked in full when it is loaded, before any of it is used:

- **Problems** stop the load, so nothing from the file can reach a project.
  Examples: not valid JSON, no version statement, a newer version, a field of
  the wrong type. Each problem gives its location, such as
  `lists[1].items[0].daughters[2] (Visual).discussion[1]`.
- **Notes** let the load go ahead. Examples: an unknown field (often a typo),
  an item class this version can't import, or a repeated `original_guid`.

Before an import, the target project is checked too, and the confirmation
dialog lists anything that would be skipped or simplified:

- items already in the list
- writing systems or character styles the target project doesn't have
- Status, Confidence, People or Restrictions items it can't find

Nothing is written until you confirm.

## Top level

| Field | Type | Notes |
|---|---|---|
| `format`, `format_version` | text, number | The version statement (above). |
| `generator` | text | Optional. The app version that wrote the file. |
| `source_project` | text | Optional. Shown when the file is loaded. |
| `description` | text | Optional. A template is listed in the app by this, e.g. "LTTW Papua (Seth)". |
| `lists` | list of lists | Version 3 only: one entry per list, each with the list fields below (at least one list). |

## List fields

In version 3 these fields are in each entry of `lists`. In versions 1 and 2,
which hold a single list, they are at the top level instead.

| Field | Type | Notes |
|---|---|---|
| `source_list_guid` | text | GUID of the list the items came from. Used first to find the target list. May be `""`. |
| `source_list_owner` | text | The field that owns that list, such as `DsDiscourseData.ChartMarkers`. Used next: it finds a built-in list even when its GUID differs between projects. |
| `source_list_name` | writing system → text | Used last, to match by name. If nothing matches, the app asks which list to import into. |
| `items` | list of items | Top-level items to import into that list (at least one). |

A version 3 file with two lists looks like this (items shortened):

```json
{
  "format": "flex-list-migrator",
  "format_version": 3,
  "source_project": "My project",
  "lists": [
    {"source_list_owner": "DsDiscourseData.ChartMarkers",
     "source_list_name": {"en": "Text Chart Markers"},
     "items": [{"name": {"en": "Evidentials"}, "abbr": {"en": "EVID"}}]},
    {"source_list_owner": "LangProject.TextMarkupTags",
     "source_list_name": {"en": "Text Markup Tags"},
     "items": [{"name": {"en": "Topic"}, "abbr": {"en": "TOP"}}]}
  ]
}
```

## Items

All fields except `name` are optional.

| Field | Type | FLEx field |
|---|---|---|
| `name` | writing system → text | Name |
| `abbr` | writing system → text | Abbreviation |
| `desc` | writing system → text | Description, as plain text |
| `desc_runs` | writing system → runs | Description with formatting. Only needed if the text mixes writing systems or uses a character style. |
| `discussion` | list of paragraphs | Discussion. Each paragraph is text or a list of runs. Without a `ws`, text uses the project's default analysis writing system. |
| `status` | reference | Status (an item in the Status list) |
| `confidence` | reference | Confidence (an item in Confidence Levels) |
| `researchers` | list of references | Researchers (items in People) |
| `restrictions` | list of references | Restrictions (items in Restrictions) |
| `daughters` | list of items | Subitems |
| `cls` | text | LCM class. Defaults to `CmPossibility`, the only class this version can import. |
| `original_guid` | text | Identifies the item inside this tool only. Imported items get new FLEx GUIDs. Filled in if missing. |

**Writing system → text** is an object keyed by writing system code:
`{"en": "Visual", "id": "Visual"}`. On import, a writing system that the target
project doesn't have is skipped, and the import notes say so.

**Runs** are pieces of text with their own writing system and character style:

```json
[{"text": "The verb "}, {"text": "wiri", "ws": "fau"}, {"text": " is marked.", "style": "Emphasized Text"}]
```

A run can also be plain text (`"text only"`).

**References** point to an item in another list: `{"guid": "…", "name": {"en": "Confirmed"}}`,
or just `"Confirmed"`. On import, the target project's list is searched by GUID,
then by name. A reference that isn't found is left out, and the import notes
say which one.

## Not carried

FLEx doesn't show these for list items, and LCM sets or manages them itself:

- SortSpec and HelpId
- the overlay colours and the Hidden flag
- IsProtected
- the created and modified dates

Fields that only some item classes have, such as a Part of Speech's inflection
features, are not carried either.

## Tips for Text Chart Markers

These points come from FLEx's own code and help:

- Each top-level item becomes a **Mark …** command in the Text Chart's cell
  menu, and its subitems become submenus. **Only items with no subitems can be
  chosen.** An item that has subitems is just a submenu heading.
- The chart cell shows the chosen item's **Abbreviation**, coloured and in
  parentheses. The menu shows *Name (Abbreviation)*. The abbreviation must be in
  the project's **default analysis writing system** to appear in the chart.
- Name and Abbreviation are plain text. Description is one paragraph and can
  mix writing systems and character styles. Discussion can have several
  paragraphs.
