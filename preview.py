#!/usr/bin/env python3
"""Render a screen config with sample data.

  python preview.py screens/subway.json            # live preview (emulator window off-Pi, matrix on the Pi)
  python preview.py screens/subway.json --png out.png   # save one frame (emulator only)
"""
import argparse
import json
import os
import time

from matrix_ui import DataModel, Surface
from matrix_ui.backend import IS_EMULATED, graphics, load_fonts, make_matrix


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("screen")
    ap.add_argument("--data", help="sample data JSON (default: <screen>.sample_data.json)")
    ap.add_argument("--png", help="write a single frame to this PNG and exit (emulator only)")
    args = ap.parse_args()

    data_path = args.data or os.path.splitext(args.screen)[0] + ".sample_data.json"
    dm = DataModel(json.load(open(data_path)) if os.path.exists(data_path) else {})

    surface = Surface.load(args.screen)       # fails fast on a bad config
    matrix = make_matrix()
    fonts = load_fonts()
    canvas = matrix.CreateFrameCanvas()

    if args.png:
        from PIL import Image
        canvas.Clear()
        surface.render(canvas, dm, fonts, graphics, strict=True)
        # The emulator keeps its pixel buffer private; there is no public readback.
        Image.fromarray(canvas._Canvas__pixels, "RGB").resize((512, 512), Image.NEAREST).save(args.png)
        print(f"wrote {args.png}")
        return

    try:
        while True:
            canvas.Clear()
            surface.render(canvas, dm, fonts, graphics)
            canvas = matrix.SwapOnVSync(canvas)
            time.sleep(0.1)
    except KeyboardInterrupt:
        matrix.Clear()


if __name__ == "__main__":
    main()
