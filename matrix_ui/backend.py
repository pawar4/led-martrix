"""Picks the real rgbmatrix bindings on the Pi, the emulator everywhere else."""
import os

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics
    IS_EMULATED = False
except ImportError:
    from RGBMatrixEmulator import RGBMatrix, RGBMatrixOptions, graphics
    IS_EMULATED = True

REPO_FONTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
PI_FONTS = "/usr/local/share/rpi-rgb-led-matrix/fonts"

# Logical font names used in screen configs -> BDF files.
FONT_FILES = {"tiny": "4x6.bdf", "small": "5x8.bdf", "large": "6x10.bdf"}


def make_matrix(brightness=60):
    options = RGBMatrixOptions()
    options.rows = 64
    options.cols = 64
    options.chain_length = 1
    options.parallel = 1
    options.hardware_mapping = 'regular'
    options.gpio_slowdown = 4
    options.brightness = brightness
    return RGBMatrix(options=options)


def load_fonts(fonts_dir=None):
    """Load the named fonts. Search order: argument, $MATRIX_FONTS_DIR, repo fonts/, Pi install."""
    candidates = [fonts_dir, os.environ.get("MATRIX_FONTS_DIR"), REPO_FONTS, PI_FONTS]
    for directory in candidates:
        if directory and all(os.path.exists(os.path.join(directory, f)) for f in FONT_FILES.values()):
            break
    else:
        raise FileNotFoundError(f"BDF fonts {sorted(FONT_FILES.values())} not found in {candidates}")

    fonts = {}
    for name, filename in FONT_FILES.items():
        font = graphics.Font()
        font.LoadFont(os.path.join(directory, filename))
        fonts[name] = font
    return fonts
