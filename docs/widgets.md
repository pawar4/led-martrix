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
| `Icon` | `name` or `weather_code` | 10x10 pixel art; `weather_code` is an Open-Meteo code |
| `Divider` | `color`, `orientation` (horizontal/vertical) | A one-pixel line through the middle of its box |
| `TrainBadge` | `route` (required), `color`, `radius` (6) | Coloured circle with the route letter; colour defaults to the MTA route colour |
| `TrainRow` | `route` (required), `name`, `arrivals` (list of minutes) | Badge, station name, next arrivals; yellow when the first is 2 min or less, "No data" when empty |
| `ForecastSlot` | `hour`, `weather_code`, `temp`, `hour_color` (dim), `temp_color` (white) | Weather icon, hour label and temperature; sized for a 32x14 box or taller (two per row) |
| `LineChart` | `values` (list of numbers), `color` (green), `fill`, `baseline`, `baseline_color` (dim grey) | Line stretched across the box, min at the bottom and max at the top; `fill` shades under the line; `baseline` is a dashed line included in the scale |

| `Fill` | `color` (black) | Solid rectangle; first child of a `Stack` makes a background |
| `ProgressBar` | `value` (0 to 1, clamped), `color` (green), `track` | Bar filled left to right; `track` is the colour of the unfilled part (transparent if unset) |
| `WrapText` | `text`, `color` (white), `font` (small), `align` (left), `line_gap` (1), `scroll` (0) | Word-wrapped to its box, one line per font height + `line_gap`. Text taller than the box shows a window of whole lines: `scroll` (0 to 1) picks it, 0 the first lines and 1 the last. Bind `scroll` to a value that changes over time to animate it. A word wider than the box is split |

`TrainRow` expects roughly 22px of height: the name sits on the row's midline and arrivals 10px below.
