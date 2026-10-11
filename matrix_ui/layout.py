from collections import namedtuple

Rect = namedtuple("Rect", "x y w h")


def inset(rect, padding):
    """padding is an int or (top, right, bottom, left)."""
    t, r, b, l = (padding,) * 4 if isinstance(padding, int) else padding
    return Rect(rect.x + l, rect.y + t, max(0, rect.w - l - r), max(0, rect.h - t - b))


def split(rect, axis, sizes, gap=0, padding=0):
    """Divide rect among children along axis ("x" or "y").

    sizes holds a fixed pixel size or None (flexible) per child. Flexible children
    share whatever space the fixed ones and the gaps leave, the last taking the remainder.
    """
    inner = inset(rect, padding)
    length = inner.w if axis == "x" else inner.h
    n = len(sizes)
    fixed = sum(s for s in sizes if s is not None) + gap * max(0, n - 1)
    flex = [i for i, s in enumerate(sizes) if s is None]
    free = max(0, length - fixed)

    rects = []
    pos = 0
    for i, size in enumerate(sizes):
        if size is None:
            size = free // len(flex) + (free % len(flex) if i == flex[-1] else 0)
        if axis == "x":
            rects.append(Rect(inner.x + pos, inner.y, size, inner.h))
        else:
            rects.append(Rect(inner.x, inner.y + pos, inner.w, size))
        pos += size + gap
    return rects
