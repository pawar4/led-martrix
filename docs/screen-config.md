# Screen config format

A screen is a JSON object:

```json
{
  "root": "root",
  "components": [
    {"id": "root", "component": "Column", "children": ["title", "clock"]},
    {"id": "title", "component": "Text", "text": {"path": "/title"}, "height": 10},
    {"id": "clock", "component": "Clock", "format": "%H:%M"}
  ]
}
```

- `root`: the ID of the top component. It gets the whole canvas (64x64).
- `components`: a flat list. Every entry needs a unique `id` and a `component` name from the
  [catalogue](widgets.md). Containers list `children` by ID. Every component must be reachable from
  `root`, and each can have only one parent (no cycles).

## Props

Each prop is either:

- a literal: `"color": "yellow"`, `"radius": 6`
- a binding to the data model: `{"path": "/trains/E/name"}`
- an explicit literal: `{"literal": "text"}`

Paths are JSON-pointer style (`/a/b/0`). A path with no data uses the widget's default for that prop.

## Placement props

Every component accepts `width`, `height`, `x`, `y`. They must be literal integers, not bindings.

- In a `Row`, `width` is fixed and children without one share the remaining space equally.
- In a `Column`, the same applies to `height`.
- In a `Stack`, `x`/`y` position the child and `width`/`height` size it.

## Sizing and overflow

The panel is 64x64. Fixed sizes are pixels, so they must add up to at most the parent's size. `Text`,
`Clock` and `TrainRow` trim text to their box. `TrainRow` drops trailing arrivals that don't fit, and
always keeps the first.

## Validation

`Surface.load` raises `ConfigError` with the component ID for: unknown component or prop, bad literal
value, missing required prop, missing/duplicate IDs, bad root, cycles, orphans, and children on leaf
widgets. Bound values are checked at render time. In `strict` mode (tests, `--png`) that raises. In live
mode the widget is skipped and the problem is printed once.

## Sample data

`screens/<name>.sample_data.json` holds the data model for previews. `preview.py` loads it automatically,
or pass `--data other.json` to try edge cases.
