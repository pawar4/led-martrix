# Architecture

```
screen.json ──> Surface.load ──> Node tree ──┐
                                             ├─> Surface.render ──> canvas
DataModel (/a/b paths) ──────────────────────┘
```

## Modules (`matrix_ui/`)

- `resolver.py`: `Surface.load(path|dict)` validates the config and builds the tree.
  `Surface.render(canvas, dm, fonts, graphics, now=None, strict=False)` resolves bindings and renders
  each node into its rect. `_reported` lives on the `Surface` so errors log once, not every frame.
- `catalog.py`: the widget registry and validators.
- `layout.py`: `Rect`, `inset`, `split` (fixed sizes plus flex remainder, gap, padding).
- `datamodel.py`: thread-safe `get(path, default)` / `set(path, value)`.
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

## Feeding live data

Nothing fetches data yet. A fetcher thread should call `dm.set("/trains/E/arrivals", [...])` on the shared
`DataModel`, and the render loop reads from it each frame.

## Testing

`tests/test_resolver.py` uses a fake canvas, font and graphics that record calls, so it needs no
emulator. `preview.py --png` is the visual check; it reads the emulator's private pixel buffer, so it may
break on emulator upgrades.
