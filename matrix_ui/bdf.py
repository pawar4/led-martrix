"""Minimal BDF font reader.

The native `graphics.DrawText` can't be clipped, so text that is only partly inside a `Scroll` is drawn pixel by pixel
from the font file instead. This reads just what that needs: each glyph's advance and its lit pixels.
"""
from functools import lru_cache

REPLACEMENT = 0xFFFD        # what the native DrawText draws for a character the font lacks


def _lit(hex_rows, width, height, x_off, y_off):
    """The lit pixels of a glyph bitmap (one hex string per row, leftmost pixel in the top bit), as offsets from the
    pen position on the baseline: dx to the right, dy down."""
    lit = []
    for row, text in enumerate(hex_rows):
        bits, count = int(text, 16), len(text) * 4
        lit.extend((x_off + col, row - height - y_off) for col in range(width) if bits >> (count - 1 - col) & 1)
    return tuple(lit)


@lru_cache(maxsize=None)
def load_bdf(path):
    """{codepoint: (advance, ((dx, dy), ...))} for every glyph in the font file."""
    glyphs, code, advance, box, rows = {}, None, 0, None, None
    with open(path, encoding="latin-1") as f:
        for line in f:
            word, _, rest = line.strip().partition(" ")
            if word == "STARTCHAR":
                code, advance, box, rows = None, 0, None, None
            elif word == "ENCODING":
                code = int(rest.split()[0])
            elif word == "DWIDTH":
                advance = int(rest.split()[0])
            elif word == "BBX":
                box = tuple(int(n) for n in rest.split())
            elif word == "BITMAP":
                rows = []
            elif word == "ENDCHAR":
                if code is not None and code >= 0 and box and rows is not None:
                    glyphs[code] = (advance, _lit(rows, *box))
                rows = None
            elif rows is not None and word:
                rows.append(word)
    return glyphs


def text_pixels(glyphs, text, x, baseline_y):
    """(x, y) of every lit pixel when `text` is drawn with the pen at `x` on the line `baseline_y`."""
    for char in text:
        glyph = glyphs.get(ord(char)) or glyphs.get(REPLACEMENT)
        if glyph is None:
            continue
        advance, lit = glyph
        for dx, dy in lit:
            yield x + dx, baseline_y + dy
        x += advance
