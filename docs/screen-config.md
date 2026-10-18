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
| `weather` | `lat*`, `lon*`, `units` (`fahrenheit`), `interval` (600) | `{code, is_day, temp_label}` (Open-Meteo; bind `is_day` to an `Icon` to show the moon at night) |
| `weather_forecast` | `lat*`, `lon*`, `day` (`today`), `step_hours` (3), `start_hour` (6), `end_hour` (22), `count` (6), `units` (`fahrenheit`), `interval` (1800) | `{date_label, slots: [{hour, code, is_day, temp_label, temp_color}]}` (Open-Meteo; bind a slot's `is_day` and `temp_color` to a `ForecastSlot`; `temp_color` is `blue` at or below 40F (4C), `red` at or above 85F (29C), else `yellow`) |
| `mta_alerts` | `routes*` (list, e.g. `["E", "7"]`), `interval` (120) | `{route: {label, color, headline, rank}, headline, count}`: the worst active alert per route (`All clear` green, `Svc change` yellow, `Delays` orange, `Suspended` red) and the worst alert's first sentence (MTA alerts feed, no key) |
| `daylight` | `lat*`, `lon*`, `interval` (60) | `{phase, color, progress, next_label, sunrise_label, sunset_label}`: `phase` is `day` or `night`, `progress` (0-1) how far through it, `color` yellow (day) or blue (night); sun times come from Open-Meteo (fetched a few times a day), the rest is computed each poll |
| `market_quote` | `symbol*`, `label` (the symbol), `range` (`intraday`, `3day` or `1month`), `interval` (60) | `{label, range_label, price_label, change_label, color, baseline, values, dividers}` (Yahoo Finance, no key) |
| `trivia` | `path*`, `question_seconds` (15), `reveal_seconds` (5), `questions` (5), `provider` (`local`), `difficulty` | `{category, value_label, count_label, phase, body, body_color, bar_color, progress, scroll}` (a local clue bank) |
| `nfl_scores` | `day` (`today`), `slots` (16), `columns` (2), `row_height` (29), `interval` (30) | `{date_label, message, length, games: [{away, away_score, away_color, away_accent, home, home_score, home_color, home_accent, label, detail, status_color}]}`: every game on `day`, padded to `slots` (ESPN scoreboard, no key; bind a game to a `GameCard` and `length` to a `Scroll`) |
| `mta_arrivals` | `stations*`, `walk_minutes` (0), `max_arrivals` (3), `interval` (30) | `{route: {name, direction, arrivals}}` (nyct-gtfs) |

`weather_forecast` `day` is `now`, `today`, `tomorrow` or a `YYYY-MM-DD` date (Open-Meteo forecasts go about 16 days ahead);
`step_hours` must divide 24. Slots run from `start_hour` to `end_hour` (inclusive, 0-23), so the defaults give
6am, 9am, 12pm, 3pm, 6pm, 9pm (10pm isn't a 3-hour step from 6am). "today" follows the
machine's clock. `now` is a rolling window instead: `count` slots (1-8) every `step_hours`
starting at the current hour at the location (`start_hour`/`end_hour` are ignored), e.g. 2pm, 5pm, 8pm, 11pm, 2am, 5am;
`date_label` is today's date there.

`mta_alerts` ignores station notices and extra service, and only counts alerts active right now. `daylight`
times are local to the given coordinates. Bind `progress` and `color` to a `ProgressBar` for a daylight bar.

`market_quote` `range` picks the chart: `intraday` is today's session at 5-minute steps, with the change measured
against the previous close; `3day` is the last three trading days at 15-minute steps, with the change measured
from the first point; `1month` is the last month of daily closes (about 21 points), also measured from the first
point. `color` is `green` or `red` (bind it to the chart and change line), `baseline` is the
reference price, `values` is the price series for `LineChart`, and `dividers` are the indexes where a new trading day starts, or a new week on `1month` (bind to `LineChart` `dividers` for 1px day-split or week-split columns on `3day` and `1month`). Symbols are Yahoo's (`^GSPC`, `AAPL`, `BTC-USD`).
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

`nfl_scores` lists every game on `day` (`today`, `tomorrow` or a `YYYY-MM-DD` date; "today" follows the machine's
clock; ESPN files a game under the US date it kicks off on), earliest kickoff first, all of them at once: the screen
puts its cards in a [`Scroll`](widgets.md#layout) and the day's slate slowly scrolls past (a slate that fits stays
still). `slots` is how many cards the screen binds (`games/0` to `games/15` in `screens/nfl.json`: eight rows of two,
32x27 each, 2px apart; games past `slots` aren't shown) and `columns` is how many sit in a row. `length` is how far
down the rows that hold a game reach, `row_height` pixels each (the card plus the gap), so a day with five games
publishes 145 and the `Scroll` stops there instead of scrolling through empty cards. Scores are refetched
once they are `interval` seconds old, shared through the same cache as the polling sources, so rotating back to the
screen doesn't refetch; if a refresh fails the last scores stay up and the next try is `interval` seconds later.
Until the first fetch works nothing is published, so the screen shows its loading placeholders (still, not scrolling).

Each game is the away team, then the home team, and binds straight onto a [`GameCard`](widgets.md#leaves).
`away_score` and `home_score` are empty until kickoff. `label` and `detail` are the card's status line: the kickoff
time in the machine's timezone (`1:00 PM`, no detail) before the game, the quarter and the clock (`Q3`, `7:46`)
during it, `HALF` at halftime, and `FINAL` or `F/OT` after; postponed, canceled, delayed and suspended games show
`PPD`, `CNCL`, `DLY` and `SUSP`. `status_color` goes with it (cyan before, green during, grey after, orange for the
rest); bind it to the card's `color`, which also sets its border. `away_color` and `home_color` are white, or
grey for the team that is behind or lost, so the leader stands out (a tie keeps both white). `away_accent` and
`home_accent` are each team's ESPN colour as an `[r, g, b]` list, with the hue kept and the brightness raised, since
most team colours are too dark to see on the panel (a near-black primary uses the team's alternate colour; a team with
no colours gets grey).
Slots with no game are blank games rather than missing ones (a path with no data would draw a loading placeholder),
and a `GameCard` with no teams draws nothing. `message` is `No games` on a day with none (empty otherwise). `slots`,
`columns` and `row_height` must match the screen's grid, which `tests/test_sources.py` checks for `screens/nfl.json`.

`mta_arrivals` stations look like `{"E": {"stop_id": "F09", "direction": "S", "name": "Court Sq"}}`.
`${NAME}` in `http_json` URLs and headers is replaced from the environment, so keys stay out of the file.
`interval` is in seconds. Mounts must not overlap. A failed fetch keeps the last good data on screen.
Sources only run with `preview.py --live`; otherwise the screen uses its `.sample_data.json`.

## Props

Each prop is either:

- a literal: `"color": "yellow"`, `"radius": 6`
- a binding to the data model: `{"path": "/trains/E/name"}`
- an explicit literal: `{"literal": "text"}`

Paths are JSON-pointer style (`/a/b/0`). A path with no data uses the widget's default for that prop, except
that a widget showing data that hasn't arrived yet draws a shimmering gray placeholder instead (see
[widgets](widgets.md#loading)), so a screen that starts before its sources have fetched doesn't show `?` or blanks.

## Placement props

Every component accepts `width`, `height`, `x`, `y`. They must be literal integers, not bindings.

- In a `Row`, `width` is fixed and children without one share the remaining space equally.
- In a `Column`, the same applies to `height`.
- In a `Stack`, `x`/`y` position the child and `width`/`height` size it.

## Sizing and overflow

The panel is 64x64. Fixed sizes are pixels, so they must add up to at most the parent's size. `Text`,
`Clock` and `TrainRow` trim text to their box. `TrainRow` drops trailing arrivals that don't fit, and
always keeps the first.

To show more than fits, put it in a [`Scroll`](widgets.md#layout): a container with one child, given a `height`
taller than the `Scroll`'s own box, that scrolls up through it on a timer and clips what is outside. Its child is laid
out at that full height, and, being a normal subtree, can be a `Column` of anything. `Scroll` needs no data model
value: it keeps its own clock (see `screens/nfl.json`). `WrapText`'s `scroll` is the separate, data-driven way to
scroll a single block of text a line at a time (see `trivia`).

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
| `sleep` | `{"start": "23:00", "end": "07:00"}`: local-time window (may span midnight) in which the matrix is dark: brightness 0 and no screen or sources running; it wakes at `end`. Or `{"weekday": {"start": ..., "end": ...}, "weekend": {...}}` for separate windows (Saturday and Sunday are the weekend; a day with no window never sleeps), chosen by the current day, including after midnight. Wins over `screen` and `schedule`; a missing or malformed window is ignored |
| `screen` | pin a screen by name (`screens/<name>.json`); wins over the rotation |
| `schedule` | list of rules, first match wins, see [Schedule](#schedule); wins over `rotation`, loses to `screen` and `sleep` |
| `rotation` | `{"screens": ["subway", "weather"], "dwell": 20}`, seconds per screen (default 20) |
| `screens.<name>.sources.<mount>` | params merged over that screen's source with the same `mount`, e.g. `{"symbol": "AAPL"}` |

You can edit `matrix.json` by hand or from the [web page](web.md#web-page). The runner is lenient about what it
reads (it skips what it can't parse), but the page and the API refuse to write an invalid model and say why.

### Schedule

```json
"schedule": [
  {"screen": "weather", "at": "0 */15 * * * *", "for": 15},
  {"screen": "markets", "at": "15 */15 * * * *", "for": 15},
  {"screen": "markets", "at": "* 9-16 * * 1-5"},
  {"screen": "subway"}
]
```

Rules are checked top to bottom and the first one that matches right now decides the screen, so put the rarest
rules first and a rule without `at` last as the fallback. If nothing matches, `rotation` applies.

- `screen`: the screen name.
- `at`: a cron expression in the Pi's local time. Five fields (`min hour day-of-month month day-of-week`) or six
  with leading seconds. Each field takes `*`, numbers, ranges (`9-16`), lists (`1,3`) and steps (`*/15`). Day of
  week is 0 to 6 with 0 as Sunday. Omit `at` for a rule that always matches.
- `for`: seconds the rule stays active from each firing (default 60). The example above shows weather for the
  first 15 seconds of every quarter hour, markets for the next 15, markets all through weekday trading hours when
  weather isn't up, and subway otherwise.

A rule that can't be parsed (bad cron, non-positive `for`) is skipped.

Overrides go through the normal source validation. An unknown screen, bad override, or unknown mount logs an
error, sets `/status/error` and leaves the current screen running. `preview.py` still renders a single
screen and ignores the global model.
