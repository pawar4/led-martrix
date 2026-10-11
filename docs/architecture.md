# Architecture

```
screen.json ──> Surface.load ──> Node tree ──┐
                                             ├─> Surface.render ──> canvas
DataModel (/a/b paths) ──────────────────────┘
      ▲
Sources (threads, from the config's "sources") ┘
```

## Modules (`matrix_ui/`)

- `resolver.py`: `Surface.load(path|dict)` validates the config and builds the tree.
  `Surface.render(canvas, dm, fonts, graphics, now=None, strict=False)` resolves bindings and renders
  each node into its rect. `_reported` lives on the `Surface` so errors log once, not every frame.
- `catalog.py`: the widget registry and validators.
- `layout.py`: `Rect`, `inset`, `split` (fixed sizes plus flex remainder, gap, padding).
- `datamodel.py`: thread-safe `get(path, default)` / `set(path, value)`.
- `sources.py`: `Source` base class, `StaticFileSource`, `PollingSource`, the `source_type` registry and
  `build_sources` (validates the config's `sources`). Generic types: `file`, `http_json`.
- `providers.py`: service-specific source types (`weather`, `weather_forecast`, `mta_arrivals`).
- `backend.py`: uses `rgbmatrix` if installed, else `RGBMatrixEmulator`. Also `make_matrix()` and
  `load_fonts()` (searches `$MATRIX_FONTS_DIR`, repo `fonts/`, then the Pi's font path).
- `icons.py`: pixel-art icons copied from `new_subway.py`.

## Adding a widget

```python
@register("Label")
class Label(Widget):
    props = {"text": (v_text, ""), "color": (v_color, COLORS["white"])}
    required = ()

    def render(self, ctx, rect, p, node):
        draw_aligned_text(ctx, rect, p["text"], p["color"], "small", "left")
```

Props are `{name: (validator, default)}`. A validator returns the normalised value or raises
`ValueError`. Set `container = True` for widgets with children. Then add a test and list the widget in
[widgets.md](widgets.md).

## Adding a data source

Sources live in `matrix_ui/sources.py` (generic) and `matrix_ui/providers.py` (service-specific). Register
a type with its params and a factory returning a `Source`; the screen config can then use it:

```python
@source_type("stocks", symbol=(v_str, REQUIRED), interval=(v_interval, 60))
def _stocks(mount, symbol, interval):
    return PollingSource(lambda: fetch_quote(symbol), interval, mount)
```

A source owns one subtree and replaces it with a single `dm.set(mount, value)`, so a render never sees a
half-updated value. Push-style sources (MQTT, WebSocket) subclass `Source` and implement `_run`.

## Testing

`tests/test_resolver.py` uses a fake canvas, font and graphics that record calls, so it needs no
emulator. `preview.py --png` is the visual check; it reads the emulator's private pixel buffer, so it may
break on emulator upgrades.
