#!/usr/bin/env python3
"""Run the matrix from the global model.

  python run.py                     # sample data, controlled by matrix.json
  python run.py --live              # real data from each screen's "sources"
  python run.py --config other.json --screens screens

Edit the config file while it runs (screen, rotation, brightness, power, per-screen source params) and the
matrix follows. See matrix_ui/app.py for the model layout.
"""
import argparse
import logging
import time

from matrix_ui import App, DataModel, StaticFileSource
from matrix_ui.backend import graphics, load_fonts, make_matrix


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="matrix.json", help="global model file, mounted at /app (default: matrix.json)")
    ap.add_argument("--screens", default="screens", help="directory of <name>.json screens")
    ap.add_argument("--live", action="store_true", help="run each screen's sources instead of its sample data")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)

    model = DataModel()
    config = StaticFileSource(args.config, mount="/app").start(model)
    app = App(model, args.screens, live=args.live)

    matrix = make_matrix()
    fonts = load_fonts()
    canvas = matrix.CreateFrameCanvas()
    brightness = None
    try:
        while True:
            app.update()
            wanted = app.brightness()
            if wanted is not None and wanted != brightness:
                matrix.brightness = brightness = wanted
            canvas.Clear()
            app.render(canvas, fonts, graphics)
            canvas = matrix.SwapOnVSync(canvas)
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        config.stop()
        app.stop()
        matrix.Clear()


if __name__ == "__main__":
    main()
