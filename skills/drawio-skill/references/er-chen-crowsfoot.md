# Conceptual ER diagrams: Chen and crow's foot (`erdgen.py`)

`sqlerd.py` draws **tables** from SQL (the relational schema). `erdgen.py` draws the **conceptual ER model** before any tables exist, in the two notations taught in database courses:

- **Chen**: rectangles, diamonds, attribute ellipses, double lines for full participation.
- **Crow's foot**: entity boxes joined by lines with bar / circle / crow's-foot ends.

One JSON model can be drawn in either notation.

```bash
python3 scripts/erdgen.py model.json --check                      # checks only, exit 1 on errors
python3 scripts/erdgen.py model.json -o model-chen.drawio         # Chen (default)
python3 scripts/erdgen.py model.json -o model-cf.drawio --notation crowsfoot
python3 scripts/erdgen.py model.json -o model.drawio --url        # also print a diagrams.net edit link
python3 scripts/validate.py model-chen.drawio --strict            # structural check of the XML
```

Worked examples are in `examples/erd-chen/`: `olympics.json` (COM106 Lecture 3 example, exactly as given: 1:N, M:N with relationship attributes, COUNTRY's attributes) and `features.json` (every Chen symbol).

## Model format

```json
{
  "title": "Olympic Games",
  "notation": "chen",
  "entities": [
    {"name": "COUNTRY", "attributes": [
      {"name": "country_code", "key": true},
      {"name": "country_name"},
      {"name": "number_of_competitors", "derived": true}]},
    {"name": "DEPENDANT", "weak": true, "attributes": [
      {"name": "dependant_name", "partial_key": true}]}
  ],
  "relationships": [
    {"name": "Sends", "identifying": false,
     "ends": [
       {"entity": "COUNTRY",    "card": "1", "participation": "full"},
       {"entity": "COMPETITOR", "card": "N", "participation": "full"}],
     "attributes": []}
  ]
}
```

| Field | Meaning | Chen | Crow's foot |
|---|---|---|---|
| entity | thing the business stores facts about | rectangle | box with the name on top |
| `"weak": true` | identified only through its owner | double rectangle | no symbol: drawn as a normal box (note printed) |
| `"key": true` | identifier | underlined ellipse | underlined attribute |
| `"partial_key": true` | identifies a weak entity *within* its owner | dashed underline | plain attribute |
| `"multivalued": true` | several values per occurrence | double ellipse | no symbol: plain attribute (note printed) |
| `"derived": true` | can be calculated from other data | dashed ellipse | no symbol: plain attribute (note printed) |
| `"parts": [...]` | composite attribute | ellipse with child ellipses | its parts listed as attributes |
| entity `"at": [col, row]` | optional: pin the entity to a grid cell | position | position |
| relationship | association between entities | diamond | line with the name beside it |
| `"identifying": true` | relationship that identifies a weak entity | double diamond | no symbol: normal line |
| end `"card"` | `1`, `N` or `M`, written **beside that end's entity** | label beside the line | max symbol beside the entity |
| end `"participation"` | must **every** occurrence of that entity take part? | double line = full, single = partial | sets the **min** symbol at the *other* end |
| relationship `"attributes"` | facts about the pairing (usually only on M:N) | ellipses on the diamond | can't be drawn: model the relationship as an associative entity (note printed) |

An entity may be listed with no attributes yet (as in the lecture example, where only COUNTRY's attributes are given): the checker warns `W-NO-ATTRS` rather than failing.

No title or legend is added to the diagram. The diagram's page name in draw.io is the model's `"title"`.

### Reading an end
`{"entity": "COMPETITOR", "card": "N"}` puts **N** beside COMPETITOR: one country sends **N** competitors. Ask the question both ways ("one country → how many competitors? one competitor → how many countries?") and write each answer beside the entity it counts.

### Chen → crow's foot conversion (what the script does)
Beside entity X on a line between X and Y:
- **max** (bar or crow's foot) comes from X's own `card`: `1` → one, `N`/`M` → many.
- **min** (bar or circle) comes from **Y's participation**: if every Y must take part, each Y has at least one X → min 1. If not → min 0.

| min, max | draw.io arrow |
|---|---|
| 1, one | `ERmandOne` |
| 0, one | `ERzeroToOne` |
| 1, many | `ERoneToMany` |
| 0, many | `ERzeroToMany` |

## What `--check` reports
It looks for missing or inconsistent structure. It never judges whether a design choice suits the scenario; that's the modeller's job.

| Code | Meaning |
|---|---|
| `E-NO-KEY` | strong entity without an identifier |
| `E-UNKNOWN-ENTITY` | relationship end names an entity that isn't declared (often a typo) |
| `E-NO-CARD` / `E-NO-PARTICIPATION` | an end is missing its cardinality or participation |
| `E-WEAK-NO-OWNER` | weak entity with no identifying relationship |
| `E-WEAK-PARTIAL` | weak entity with partial participation in its identifying relationship |
| `E-ID-NO-WEAK` | identifying relationship linking no weak entity |
| `E-BAD-KEY` | key that is multi-valued or derived |
| `W-WEAK-NO-PARTIAL-KEY` | weak entity without a partial key |
| `W-REL-ATTR-1N` | attributes on a 1:1 / 1:N relationship (usually belong to the N side) |
| `W-ISOLATED` | entity in no relationship |
| `W-NO-ATTRS` | no attributes listed yet |
| `W-ONE-ATTR` | only one attribute: is it really an entity? |

## Layout
No external tools needed. The script lays the diagram out the way lecture diagrams are drawn:

1. **Entities on a grid.** A small search tries arrangements and keeps the one where related entities are next to each other (straight lines, no crossings, no line running through another entity).
2. **Diamonds in between.** Each relationship diamond sits halfway between its entities. Two relationships between the same pair are spread apart.
3. **Attributes fan out away from the lines.** Each entity's attributes go in the gaps between its relationship lines and are pushed outwards if they would overlap anything.

Crow's foot uses the same grid, with rows and columns aligned so the lines run straight.

**Pin an entity** to a grid cell with `"at": [column, row]` (0-based, top-left is `[0, 0]`), e.g. `{"name": "CUSTOMER", "at": [0, 0], ...}`. The others are arranged around it. The output is a normal `.drawio` file, so you can still drag shapes in draw.io and the lines stay attached.

Crow's foot draws only binary relationships, as the notation requires. Chen also draws 3+ way relationships (diamond at the centre of its entities).
