from collections import namedtuple

Rect = namedtuple("Rect", "x y w h")


def inset(rect, padding):
    """padding is an int or (top, right, bottom, left)."""
    t, r, b, l = (padding,) * 4 if isinstance(padding, int) else padding
    return Rect(rect.x + l, rect.y + t, max(0, rect.w - l - r), max(0, rect.h - t - b))


def intersect(a, b):
    """The area two rects share (zero-sized when they don't overlap)."""
    x, y = max(a.x, b.x), max(a.y, b.y)
    return Rect(x, y, max(0, min(a.x + a.w, b.x + b.w) - x), max(0, min(a.y + a.h, b.y + b.h) - y))


def touches(rect, other, margin=0):
    """True if `rect`, grown by `margin` pixels on every side, overlaps `other`."""
    return (rect.x - margin < other.x + other.w and other.x < rect.x + rect.w + margin
            and rect.y - margin < other.y + other.h and other.y < rect.y + rect.h + margin)


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
