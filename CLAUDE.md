# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Config-driven screens for a 64x64 Raspberry Pi RGB LED matrix. A screen is a JSON file (flat component list, children by ID, props are literals or data-model bindings); `matrix_ui/resolver.py` validates it and renders it using widgets from `matrix_ui/catalog.py`. `new_subway.py` is the original hardcoded script — leave it untouched.

## Commands

```bash
source .venv/bin/activate
pytest tests/                                  # all tests
pytest tests/test_resolver.py -k <name>        # single test
python preview.py screens/subway.json          # emulator at http://localhost:8888
python preview.py screens/subway.json --png out.png   # one frame to PNG
python preview.py screens/subway.json --live  # run the screen's "sources" (real data) instead of sample data
```

Off-Pi uses RGBMatrixEmulator; on the Pi `matrix_ui.backend` prefers the real `rgbmatrix` bindings.

## Notes

- Each `screens/<name>.json` has a `<name>.sample_data.json` used by previews. A screen declares its live data in a top-level `sources` list (types in `matrix_ui/sources.py` and `providers.py`).
- Details live in `docs/`: `screen-config.md` (format), `widgets.md` (catalogue), `architecture.md` (extending).
- When you change logic (config format, widgets, data sources, CLI flags), update the relevant docs in the same change: `docs/screen-config.md`, `docs/widgets.md`, `docs/architecture.md`, and `README.md` where it applies.
