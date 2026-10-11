# led-martrix

Config-driven screens for a 64x64 Raspberry Pi RGB LED matrix. A screen is a JSON file: a flat list of
components (A2UI-style, children referenced by ID) whose props are literals or bindings into a data model.
A resolver validates the config and renders it with a catalogue of matrix-specific widgets.

`new_subway.py` is the original hardcoded script. It is untouched and still runs on its own.

## Quick start (off-Pi, with the emulator)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest tests/
python preview.py screens/subway.json              # emulator in the browser, http://localhost:8888
python preview.py screens/subway.json --png out.png   # one frame, saved as a PNG
python preview.py screens/weather.json             # 3-hour forecast for one day (set "day" in its source)
python preview.py screens/subway.json --live          # real MTA + weather data (sources declared in the screen config)
```

On the Pi, install the real `rgbmatrix` bindings; `matrix_ui.backend` uses them in preference to the emulator.

## Layout

| Path | What |
|---|---|
| `matrix_ui/` | The resolver package (config loading, widgets, layout, data model, data sources, icons, backend) |
| `screens/` | Screen configs, each with a `<name>.sample_data.json` for previews |
| `preview.py` | Render a screen with sample data, or live data with `--live` |
| `tests/` | pytest suite |
| `docs/` | Documentation |
| `fonts/` | BDF fonts (4x6, 5x8, 6x10) |

## Docs

- [Screen config format](docs/screen-config.md)
- [Widget catalogue](docs/widgets.md)
- [Architecture and extending](docs/architecture.md)

## Not done yet

Live sources for the markets and riddle screens, porting the markets/riddle/Bondi screens, screen scheduling,
and AI authoring of screens.
