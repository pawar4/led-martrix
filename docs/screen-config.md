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

## Data sources

A screen can declare where its data comes from with an optional top-level `sources` list. Each source
writes into the data model under its own `mount` path, and the component bindings read from there.

```json
"sources": [
  {"type": "weather", "mount": "/weather", "lat": 40.71, "lon": -74.0, "interval": 600},
  {"type": "http_json", "mount": "/api", "url": "https://example.com/x?key=${MY_KEY}", "interval": 60}
]
```

| type | params (`*` required) | publishes |
|---|---|---|
| `file` | `path*`, `interval` (0.5) | the JSON file's contents; reloaded when it changes |
| `http_json` | `url*`, `headers`, `interval` (30) | the response body |
| `weather` | `lat*`, `lon*`, `units` (`fahrenheit`), `interval` (600) | `{code, temp_label}` (Open-Meteo) |
| `weather_forecast` | `lat*`, `lon*`, `day` (`today`), `step_hours` (3), `start_hour` (6), `end_hour` (22), `units` (`fahrenheit`), `interval` (1800) | `{date_label, slots: [{hour, code, temp_label}]}` (Open-Meteo) |
| `market_quote` | `symbol*`, `label` (the symbol), `range` (`intraday`), `interval` (60) | `{label, range_label, price_label, change_label, color, baseline, values}` (Yahoo Finance, no key) |
| `mta_arrivals` | `stations*`, `walk_minutes` (0), `max_arrivals` (3), `interval` (30) | `{route: {name, arrivals}}` (nyct-gtfs) |

`weather_forecast` `day` is `today`, `tomorrow` or a `YYYY-MM-DD` date (Open-Meteo forecasts go about 16 days ahead);
`step_hours` must divide 24. Slots run from `start_hour` to `end_hour` (inclusive, 0-23), so the defaults give
6am, 9am, 12pm, 3pm, 6pm, 9pm (10pm isn't a 3-hour step from 6am). "today" follows the
machine's clock.

`market_quote` `range` picks the chart: `intraday` is today's session at 5-minute steps, with the change measured
against the previous close; `3day` is the last three trading days at 15-minute steps, with the change measured
from the first point. `color` is `green` or `red` (bind it to the chart and change line), `baseline` is the
reference price, and `values` is the price series for `LineChart`. Symbols are Yahoo's (`^GSPC`, `AAPL`, `BTC-USD`).
To switch charts, change `range` in the screen's source. Outside market hours the intraday chart shows the last
session.

`mta_arrivals` stations look like `{"E": {"stop_id": "F09", "direction": "S", "name": "Court Sq"}}`.
`${NAME}` in `http_json` URLs and headers is replaced from the environment, so keys stay out of the file.
`interval` is in seconds. Mounts must not overlap. A failed fetch keeps the last good data on screen.
Sources only run with `preview.py --live`; otherwise the screen uses its `.sample_data.json`.

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
or pass `--data other.json` to try edge cases. In the live preview the file is a `file` source, so edits
show up on screen without a restart. `--png` loads it once. `--live` ignores it and runs the screen's
[`sources`](#data-sources) instead.
