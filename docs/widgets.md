# Widget catalogue

Defined in [`matrix_ui/catalog.py`](../matrix_ui/catalog.py). All widgets also accept `width`, `height`,
`x`, `y` (see [screen-config](screen-config.md)).

Colours are a name (`white`, `yellow`, `green`, `red`, `dim`, `cyan`, `orange`, `blue`, `purple`, `magenta`, `pink`, `lime`, `teal`, `black`) or `[r, g, b]`.
Fonts are `tiny` (4x6), `small` (5x8) or `large` (6x10).

## Layout

| Component | Props | Notes |
|---|---|---|
| `Column` | `gap` (0), `padding` (0) | Stacks children top to bottom |
| `Row` | `gap` (0), `padding` (0) | Lays children left to right |
| `Stack` | `padding` (0) | Overlays children, each at its own `x`/`y` |

`padding` is an int or `[top, right, bottom, left]`.

## Leaves

| Component | Props | Notes |
|---|---|---|
| `Text` | `text`, `color` (white), `font` (small), `align` (left/center/right) | Trimmed to its box |
| `Clock` | `format` (`%H:%M`), `color`, `font`, `align` | strftime format, current time |
| `Icon` | `name` or `weather_code`, `is_day` (true) | 10x10 pixel art; `name` is one of `sun`, `moon`, `partly_cloudy`, `partly_cloudy_night`, `cloud`, `fog`, `rain`, `snow`, `storm`, `unknown`; `weather_code` is an Open-Meteo code, and with `is_day` false code 0 (clear) shows the moon and code 1 (mainly clear) the moon behind a cloud |
| `Divider` | `color`, `orientation` (horizontal/vertical) | A one-pixel line through the middle of its box |
| `TrainBadge` | `route` (required), `color`, `radius` (6) | Coloured circle with the route letter; colour defaults to the MTA route colour |
| `TrainRow` | `route` (required), `name`, `arrivals` (list of minutes), `direction` (`N`, `S` or empty), `alert` (colour) | Badge, station name, next arrivals; `direction` draws a cyan arrow in the badge column: up (`N`, uptown) above the badge, down (`S`, downtown) below it; `alert` draws a 3px status dot at the badge's top-right corner (nothing when green, so bind it to an `mta_alerts` colour); yellow when the first is 2 min or less, "No data" when empty |
| `ForecastSlot` | `hour`, `weather_code`, `is_day` (true), `temp`, `hour_color` (dim), `temp_color` (white) | Weather icon (moon icons for clear and mainly clear skies when `is_day` is false), hour label and temperature; sized for a 32x14 box or taller (two per row) |
| `LineChart` | `values` (list of numbers), `color` (green), `fill`, `baseline`, `baseline_color` (dim grey), `dividers` (list of indexes into `values`), `divider_color` (dim grey) | Line stretched across the box, min at the bottom and max at the top; `fill` shades under the line; `baseline` is a dashed line included in the scale; each `dividers` index gets a 1px full-height column behind the line (e.g. a day split) |

| `Fill` | `color` (black) | Solid rectangle; first child of a `Stack` makes a background |
| `ProgressBar` | `value` (0 to 1, clamped), `color` (green), `track` | Bar filled left to right; `track` is the colour of the unfilled part (transparent if unset) |
| `WrapText` | `text`, `color` (white), `font` (small), `align` (left), `line_gap` (1), `scroll` (0) | Word-wrapped to its box, one line per font height + `line_gap`. Text taller than the box shows a window of whole lines: `scroll` (0 to 1) picks it, 0 the first lines and 1 the last. Bind `scroll` to a value that changes over time to animate it. A word wider than the box is split |

| `Countdown` | `target` (required), `format` (`{d}d {h:02}:{m:02}:{s:02}`), `color`, `font`, `align` | Time left until `target`, an ISO date-time (`2026-12-26T11:00:00`; no offset means the machine's local time). `format` uses `{d}` days, `{h}` hours, `{m}` minutes, `{s}` seconds (hours, minutes and seconds are the remainder, so `{h}` is 0 to 23), each with an optional spec like `{h:02}`. Reads the clock like `Clock`; zeros once `target` has passed. Trimmed to its box |
| `SpeechBubble` | `fill` (near black), `border` (light grey), `tail` (true) | Filled box with an outline, rounded corners and a two-pixel tail pointing down-left, just below the box. Put text on top of it in a `Stack` |
| `Image` | `path` (required) | A picture scaled down to fit its box (aspect ratio kept, centred), read once and cached. `path` is relative to where you run from. A missing or unreadable file draws nothing and is reported once |

`TrainRow` expects roughly 22px of height: the name sits on the row's midline and arrivals 10px below.

## Loading

A widget whose main prop is bound to a path with no data yet (the source hasn't published, or the first fetch
failed) draws a placeholder instead of an empty value: dark gray bars with a light band sweeping left to right
every 1.6 seconds. It switches to the real value as soon as the data arrives. Literal props never show one, and
real but empty data still reads as empty (`TrainRow` says "No data" for an empty `arrivals` list).

| Widget | Waits on | Placeholder |
|---|---|---|
| `Text` | `text` | one bar, up to 24px wide, placed by `align` |
| `Icon` | `weather_code` | an 8x8 block (an icon picked by `name` is drawn as normal) |
| `TrainRow` | `name`, `arrivals` | the badge, arrow and dot draw as normal; the name and arrivals lines are bars |
| `ForecastSlot` | `hour`, `weather_code`, `temp` | an icon block and two bars |
| `LineChart` | `values` | a thin bar across the middle |
| `ProgressBar` | `value` | a thin bar across the whole box |
| `WrapText` | `text` | two bars, the second shorter |

To give a new widget one, set `loading_props` on the class and override `render_loading` (the default draws one
bar); use `draw_skeleton(ctx, x, y, w, h)` to draw the shimmer.
