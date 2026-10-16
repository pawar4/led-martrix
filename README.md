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
python preview.py screens/weather.json             # daylight bar + next 18 hours in 3-hour steps (set "day" to today/tomorrow for a fixed day)
python preview.py screens/markets.json             # price + filled chart (set "range" to intraday or 3day in its source)
python preview.py screens/trivia.json             # Jeopardy-style clue, timer bar, then the answer (clues in screens/trivia.clues.json, or set "provider": "opentdb" in its source for online questions)
python preview.py screens/guest.json              # "guest leaves in" countdown over a picture (put it at assets/tanner.png, set the date in the screen's "target")
python serve.py                                     # web page at http://localhost:8099/ to edit matrix.json (run alongside run.py)
python run.py                                      # the global model (matrix.json) picks, rotates and configures screens; add --live for real data
python preview.py screens/subway.json --live          # real MTA + weather data (sources declared in the screen config)
```

On the Pi, install the real `rgbmatrix` bindings; `matrix_ui.backend` uses them in preference to the emulator.

## Install on the Pi

```bash
git clone <this repo> && cd led-martrix
./install.sh      # --dry-run first to see every step
```

It installs to `/opt/led-matrix`, builds the `rgbmatrix` bindings into that venv, and enables `led-matrix` (the runner,
`run.py --live`) and `led-matrix-assistant` (`serve.py`: the web page at `http://<pi>.local/`, also port 8099; it only answers the local network).
From your laptop, `./deploy.sh` does it remotely (rsync to the Pi, retire the old `new_subway.py` cron job, run `install.sh`; `--dry-run` first, `PI_HOST=user@host` to override; `--push-config` also overwrites the Pi's `matrix.json` with yours, which a plain deploy keeps because the web page edits it there). Re-run either to deploy code changes; `matrix.json` and the env file are kept. Reboot once after the first run.

## Layout

| Path | What |
|---|---|
| `matrix_ui/` | The resolver package (config loading, widgets, layout, data model, data sources, icons, backend) |
| `screens/` | Screen configs, each with a `<name>.sample_data.json` for previews |
| `assets/` | Pictures that screens load with `Image` (`tanner.png` is the guest countdown picture) |
| `serve.py`, `matrix_ui/model_store.py` | HTTP service that edits `matrix.json`: serves the control page and takes validated edits (`PATCH /model`), for the local network only. See `docs/web.md` |
| `web/` | The control page (`index.html`, no build step) |
| `deploy.sh` | Run from your laptop: syncs the repo to the Pi over SSH, removes the old `new_subway.py` `@reboot` cron entry and process, then runs `install.sh` there |
| `install.sh` | One-shot Pi setup: packages, rgbmatrix bindings, venv, systemd services |
| `scripts/set-password.sh` | Sets (or changes) the web page password: writes `MATRIX_TOKEN` to `/etc/led-matrix.env` on the Pi and restarts the service |
| `run.py`, `matrix.json` | The runner and its global model: active screen, rotation, brightness, power, sleep window, per-screen source params |
| `preview.py` | Render a screen with sample data, or live data with `--live` |
| `tests/` | pytest suite |
| `docs/` | Documentation |
| `fonts/` | BDF fonts (4x6, 5x8, 6x10) |

## Docs

- [Screen config format](docs/screen-config.md)
- [Widget catalogue](docs/widgets.md)
- [Architecture and extending](docs/architecture.md)

## Not done yet

Multi-symbol markets rotation, time-of-day screen scheduling and a remote control channel (HTTP/MQTT) writing into the global model.
The riddle and Bondi pages are retired; trivia replaces the riddle, and `screens/guest.json` is the Bondi layout (picture
plus speech bubble) rebuilt from widgets.
