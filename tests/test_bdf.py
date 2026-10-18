import os

import pytest

from matrix_ui.bdf import load_bdf, text_pixels

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = {"tiny": "4x6.bdf", "small": "5x8.bdf", "large": "6x10.bdf"}


class Recorder:
    width = height = 64

    def __init__(self):
        self.lit = set()

    def SetPixel(self, x, y, r, g, b):
        self.lit.add((x, y))


@pytest.mark.parametrize("name", sorted(FONTS))
def test_text_pixels_match_what_the_native_draw_text_lights(name):
    """Partly visible text is drawn from the font file, so it has to land exactly where DrawText puts it."""
    graphics = pytest.importorskip("RGBMatrixEmulator.graphics")
    path = os.path.join(ROOT, "fonts", FONTS[name])
    font = graphics.Font()
    font.LoadFont(path)
    glyphs = load_bdf(path)
    for text in ("HOU 31", "Q4 7:46", "4:25 PM", "FINAL", "Oct 18", "+0.60%", "abcdefghij", "$%&()[]{}<>"):
        canvas = Recorder()
        graphics.DrawText(canvas, font, 3, 20, graphics.Color(255, 255, 255), text)
        assert set(text_pixels(glyphs, text, 3, 20)) == canvas.lit, text


def test_text_pixels_move_with_the_pen_and_use_the_replacement_for_unknown_characters():
    glyphs = {ord("I"): (3, ((0, -2), (1, -1))), 0xFFFD: (2, ((0, 0),))}
    assert list(text_pixels(glyphs, "II", 10, 20)) == [(10, 18), (11, 19), (13, 18), (14, 19)]
    assert list(text_pixels(glyphs, "I☃", 0, 5)) == [(0, 3), (1, 4), (3, 5)]
    assert list(text_pixels({}, "I", 0, 5)) == []
