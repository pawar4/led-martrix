# Architecture

```
screen.json ──> Surface.load ──> Node tree ──┐
                                             ├─> Surface.render ──> canvas
DataModel (/a/b paths) ──────────────────────┘
      ▲
Sources (threads, from the config's "sources") ┘
```

## Global model and runner

`run.py` mounts `matrix.json` into one global `DataModel` at `/app` (reloaded when the file changes) and
hands it to `App` (`matrix_ui/app.py`), which each frame picks the screen, rebuilds it when its source
overrides change, and applies brightness. Screens keep their own per-screen `DataModel`, so their bindings
are unchanged. See [screen-config.md](screen-config.md#global-model) for the keys. `App` writes
`/status/active` and `/status/error` (a bad screen name or override keeps the old screen up).

## Modules (`matrix_ui/`)

- `cron.py`: `Cron`, the cron-expression matcher behind `/app/schedule` rules (`fires`, `active`, and `next` for the web page's preview).
- `app.py`: `App`, the global-model controller (screen choice, rotation, power, sleep window, brightness, per-screen source overrides).

- `model_store.py`: owns the model file for writers. `ModelStore.update(changes)` merges top-level keys into a copy of the
  model, validates it (`validate_model`: the model's shape, then `load_surface` for every screen it names, overrides
  merged), and writes the model file atomically; `undo()` restores the previous model. `serve.py` wraps it in HTTP,
  answering the local network only, and serves `web/index.html`, the control page (plain HTML and JS, no build step).
  See [web.md](web.md).
- `resolver.py`: `Surface.load(path|dict)` validates the config and builds the tree.
  `Surface.render(canvas, dm, fonts, graphics, now=None, strict=False)` resolves bindings and renders
  each node into its rect. `_reported` lives on the `Surface` so errors log once, not every frame. A `Node`
  keeps per-frame widget state in `node.state` (a `Scroll`'s start time); it is lost when the screen reloads.
- `catalog.py`: the widget registry and validators.
- `layout.py`: `Rect`, `inset`, `split` (fixed sizes plus flex remainder, gap, padding), `intersect`, `touches`.
- `clip.py`: `ClipCanvas`, a canvas wrapper that drops `SetPixel` outside a `Rect`. `Scroll` swaps it in for
  `ctx.canvas` while it renders its child, so every widget that draws with `SetPixel` is clipped without knowing.
  `ctx.clip` is its rect (None outside a `Scroll`), and `render_node` skips nodes that fall wholly outside it.
  The native `graphics.DrawText` can't be clipped and rejects a wrapper canvas, so `draw_text` calls it (on the
  wrapper's `target`) only when the text is wholly in view, skips text wholly out of view, and draws text that
  straddles the edge pixel by pixel from `bdf.py`, which reads just the glyph bitmaps from the font file
  (`backend.font_file(name)`); `tests/test_bdf.py` checks it lights exactly the pixels `DrawText` does.
- `datamodel.py`: thread-safe `get(path, default)` / `set(path, value)`.
- `sources.py`: `Source` base class, `StaticFileSource`, `PollingSource`, the `source_type` registry and
  `build_sources` (validates the config's `sources`). Generic types: `file`, `http_json`.
- `providers.py`: service-specific source types (`weather`, `weather_forecast`, `market_quote`, `nfl_scores`, `trivia`, `mta_arrivals`, `mta_alerts`, `daylight`).
- `backend.py`: uses `rgbmatrix` if installed, else `RGBMatrixEmulator`. Also `make_matrix()` and
  `load_fonts()` (searches `$MATRIX_FONTS_DIR`, repo `fonts/`, then the Pi's font path; `font_dir()` is that search).
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
`ValueError`. Set `container = True` for widgets with children (and `max_children = 1` to limit how many; the
resolver rejects more). Then add a test and list the widget in
[widgets.md](widgets.md).

## Adding a data source

Sources live in `matrix_ui/sources.py` (generic) and `matrix_ui/providers.py` (service-specific). Register
a type with its params and a factory returning a `Source`; the screen config can then use it:

```python
@source_type("stocks", symbol=(v_str, REQUIRED), interval=(v_interval, 60))
def _stocks(mount, symbol, interval):
    return PollingSource(lambda: fetch_quote(symbol), interval, mount)
```

Polling sources are memoized: `build_source` gives each a key (type + params, ignoring `mount` and `interval`),
and `FETCH_CACHE` holds the last value per key. A source started within its `interval` of the last fetch
publishes the cached value at once and only fetches when it is stale; stale data is still shown while the
refetch runs. So rotating screens doesn't refetch, and two sources with the same params share data. Failed
fetches aren't cached. `trivia` and `file` sources aren't memoized. `nfl_scores` is a `Source` subclass because it
follows "today" across midnight and builds its frame from the fetched games (`nfl_frame`), which a polling source can't;
it keeps the memoization by putting its fetched scores in `FETCH_CACHE` itself (keyed by type and day) and passing a
`cache` in for tests.

A source owns one subtree and replaces it with a single `dm.set(mount, value)`, so a render never sees a
half-updated value. Push-style sources (MQTT, WebSocket) subclass `Source` and implement `_run`.

## Testing

`tests/test_resolver.py` uses a fake canvas, font and graphics that record calls, so it needs no
emulator. `preview.py --png` is the visual check; it reads the emulator's private pixel buffer, so it may
break on emulator upgrades.
