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

`interval` is also the staleness limit: fetched data is cached per type and params, and a source that restarts
(for example when the global model rotates back to its screen) reuses it until it is `interval` seconds old.

| type | params (`*` required) | publishes |
|---|---|---|
| `file` | `path*`, `interval` (0.5) | the JSON file's contents; reloaded when it changes |
| `http_json` | `url*`, `headers`, `interval` (30) | the response body |
| `weather` | `lat*`, `lon*`, `units` (`fahrenheit`), `interval` (600) | `{code, temp_label}` (Open-Meteo) |
| `weather_forecast` | `lat*`, `lon*`, `day` (`today`), `step_hours` (3), `start_hour` (6), `end_hour` (22), `units` (`fahrenheit`), `interval` (1800) | `{date_label, slots: [{hour, code, temp_label}]}` (Open-Meteo) |
| `market_quote` | `symbol*`, `label` (the symbol), `range` (`intraday`), `interval` (60) | `{label, range_label, price_label, change_label, color, baseline, values}` (Yahoo Finance, no key) |
| `trivia` | `path*`, `question_seconds` (15), `reveal_seconds` (5), `questions` (5), `provider` (`local`), `difficulty` | `{category, value_label, count_label, phase, body, body_color, bar_color, progress, scroll}` (a local clue bank) |
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

`trivia` plays one round of `questions` clues (1 to 50, default 5), then stops on the last answer (no new round, no refetch). It reads a
clue bank (a JSON list of `{category, value, clue, answer}`, relative to where you run from; see
`screens/trivia.clues.json`) and plays it in shuffled order, with no repeats until every clue has been used, even
across rounds. The bank is read once at startup.

Each clue is a `question` phase (`body` is the upper-cased clue, white, `progress` drains from 1 to 0 over
`question_seconds`) followed by a `reveal` phase (`body` is the answer, green, `progress` drains over
`reveal_seconds`). `count_label` is the position in the round (`2/5`). `scroll` (0 to 1) rests at 0 for 1.5 seconds,
moves through the text, then rests at 1 for 1.5 seconds, once per phase; bind it to `WrapText`'s `scroll` so long
clues and answers step down. `bar_color` is `yellow` then `green` and `body_color` `white` then `green`; bind them to
the widgets. The source republishes ten times a second, so the screen needs no clock.

The body box in `screens/trivia.json` shows 5 lines of about 15 characters in the 4x6 font; longer text scrolls, so a
clue of about 100 characters or more needs most of `question_seconds` to read. Keep answers short, since
`reveal_seconds` is brief.

`provider` `opentdb` plays fresh multiple-choice questions from [Open Trivia DB](https://opentdb.com) (free, no key)
instead of the bank: each round fetches `questions` questions (optionally only `difficulty` `easy`, `medium` or
`hard`) and plays them in order, fetching again for the next round. The options are appended to the clue as
`A) ... B) ... C) ... D) ...` and the reveal shows the right letter and text (`C) Mercury`). The category is the part
after the colon (`Science: Computers` becomes `Computers`), and the value follows the difficulty ($200, $600,
$1000). If a fetch fails (offline, rate limited at one request per 5 seconds, a bad response), that round plays the
local bank at `path` instead, so `path` is required either way. The screen stalls on its last frame while a fetch is
in progress, up to 10 seconds. These clues run long, so raise `question_seconds` (20 is comfortable) to leave time to
scroll through them.

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

## Global model

`python run.py [--live] [--config matrix.json] [--screens screens]` runs the matrix from one global model,
loaded from `matrix.json` and reloaded whenever the file changes:

| key | meaning |
|---|---|
| `power` | `false` blanks the matrix (default `true`) |
| `brightness` | 1 to 100 |
| `screen` | pin a screen by name (`screens/<name>.json`); wins over the rotation |
| `rotation` | `{"screens": ["subway", "weather"], "dwell": 20}`, seconds per screen (default 20) |
| `screens.<name>.sources.<mount>` | params merged over that screen's source with the same `mount`, e.g. `{"symbol": "AAPL"}` |

Overrides go through the normal source validation. An unknown screen, bad override, or unknown mount logs an
error, sets `/status/error` and leaves the current screen running. `preview.py` still renders a single
screen and ignores the global model.
