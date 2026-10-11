"""Widget catalogue: every component a screen config may use.

A widget declares its props as {name: (validator, default)}. Validators return the
(normalised) value or raise ValueError. Add a widget by subclassing Widget and
decorating it with @register("Name").
"""
from .icons import ICONS, UNKNOWN, draw_icon, get_icon_for_code
from .layout import Rect, inset, split

REGISTRY = {}

# Props every component accepts for placement inside its parent; always literal ints.
LAYOUT_PROPS = ("width", "height", "x", "y")

COLORS = {
    "white": (255, 255, 255),
    "yellow": (255, 220, 0),
    "green": (0, 220, 0),
    "red": (220, 0, 0),
    "dim": (100, 100, 100),
    "cyan": (0, 200, 200),
    "black": (0, 0, 0),
}

# MTA route bullet colours.
ROUTE_COLORS = {
    **dict.fromkeys("123", (238, 53, 46)),
    **dict.fromkeys("456", (0, 147, 60)),
    **dict.fromkeys("ACE", (0, 57, 166)),
    **dict.fromkeys("BDFM", (255, 99, 25)),
    "G": (108, 190, 69),
    **dict.fromkeys("JZ", (153, 102, 51)),
    "L": (167, 169, 172),
    **dict.fromkeys("NQRW", (252, 204, 10)),
    "7": (185, 51, 173),
}

FONT_NAMES = ("tiny", "small", "large")


# ---- validators ----

def v_text(v):
    return str(v)


def v_int(v):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError(f"expected integer, got {v!r}")
    return v


def v_color(v):
    if isinstance(v, str) and v in COLORS:
        return COLORS[v]
    if isinstance(v, (list, tuple)) and len(v) == 3 and all(isinstance(c, int) and 0 <= c <= 255 for c in v):
        return tuple(v)
    raise ValueError(f"expected one of {sorted(COLORS)} or [r, g, b], got {v!r}")


def v_oneof(*options):
    def check(v):
        if v not in options:
            raise ValueError(f"expected one of {list(options)}, got {v!r}")
        return v
    return check


def v_int_list(v):
    if not isinstance(v, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in v):
        raise ValueError(f"expected list of integers, got {v!r}")
    return v


def v_padding(v):
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    if isinstance(v, (list, tuple)) and len(v) == 4 and all(isinstance(i, int) for i in v):
        return tuple(v)
    raise ValueError(f"expected integer or [top, right, bottom, left], got {v!r}")


# ---- base ----

class Widget:
    props = {}
    required = ()
    container = False

    def render(self, ctx, rect, p, node):
        raise NotImplementedError


def register(name):
    def deco(cls):
        REGISTRY[name] = cls()
        return cls
    return deco


# ---- drawing helpers ----

def text_width(font, text):
    return sum(font.CharacterWidth(ord(c)) for c in text)


def draw_text(ctx, x, baseline_y, text, color, font_name):
    font = ctx.fonts[font_name]
    ctx.graphics.DrawText(ctx.canvas, font, x, baseline_y, ctx.graphics.Color(*color), text)


def draw_aligned_text(ctx, rect, text, color, font_name, align):
    font = ctx.fonts[font_name]
    width = text_width(font, text)
    x = rect.x
    if align == "center":
        x += (rect.w - width) // 2
    elif align == "right":
        x += rect.w - width
    draw_text(ctx, x, rect.y + font.baseline, text, color, font_name)


def draw_disc(canvas, cx, cy, radius, color):
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            if dx * dx + dy * dy <= radius * radius:
                canvas.SetPixel(cx + dx, cy + dy, *color)


def draw_badge(ctx, rect, route, color, radius):
    """Route bullet: coloured disc with the route letter, centred in rect."""
    cx, cy = rect.x + rect.w // 2, rect.y + rect.h // 2
    draw_disc(ctx.canvas, cx, cy, radius, color)
    font = ctx.fonts["large"]
    draw_text(ctx, cx - text_width(font, route) // 2, cy - font.height // 2 + font.baseline,
              route, COLORS["white"], "large")


def format_arrivals(minutes):
    return ", ".join("Now" if m == 0 else f"{m}m" for m in minutes)


# ---- layout widgets ----

class _Linear(Widget):
    container = True
    axis = "y"
    props = {"gap": (v_int, 0), "padding": (v_padding, 0)}

    def render(self, ctx, rect, p, node):
        size_key = "width" if self.axis == "x" else "height"
        sizes = [c.layout.get(size_key) for c in node.children]
        for child, child_rect in zip(node.children, split(rect, self.axis, sizes, p["gap"], p["padding"])):
            ctx.render_node(child, child_rect)


@register("Column")
class Column(_Linear):
    axis = "y"


@register("Row")
class Row(_Linear):
    axis = "x"


@register("Stack")
class Stack(Widget):
    """Overlays children; each is placed at its own x/y (default 0,0) with its own width/height."""
    container = True
    props = {"padding": (v_padding, 0)}

    def render(self, ctx, rect, p, node):
        inner = inset(rect, p["padding"])
        for child in node.children:
            x, y = child.layout.get("x", 0), child.layout.get("y", 0)
            w = child.layout.get("width", inner.w - x)
            h = child.layout.get("height", inner.h - y)
            ctx.render_node(child, Rect(inner.x + x, inner.y + y, w, h))


# ---- leaf widgets ----

@register("Text")
class Text(Widget):
    props = {
        "text": (v_text, ""),
        "color": (v_color, COLORS["white"]),
        "font": (v_oneof(*FONT_NAMES), "small"),
        "align": (v_oneof("left", "center", "right"), "left"),
    }

    def render(self, ctx, rect, p, node):
        draw_aligned_text(ctx, rect, p["text"], p["color"], p["font"], p["align"])


@register("Clock")
class Clock(Widget):
    props = {
        "format": (v_text, "%H:%M"),
        "color": (v_color, COLORS["white"]),
        "font": (v_oneof(*FONT_NAMES), "small"),
        "align": (v_oneof("left", "center", "right"), "left"),
    }

    def render(self, ctx, rect, p, node):
        draw_aligned_text(ctx, rect, ctx.now().strftime(p["format"]), p["color"], p["font"], p["align"])


@register("Icon")
class Icon(Widget):
    """10x10 pixel-art icon, picked by `name` or derived from an Open-Meteo `weather_code`."""
    props = {"name": (v_oneof(*ICONS), None), "weather_code": (v_int, None)}

    def render(self, ctx, rect, p, node):
        if p["name"] is not None:
            icon = ICONS[p["name"]]
        elif p["weather_code"] is not None:
            icon = get_icon_for_code(p["weather_code"])
        else:
            icon = UNKNOWN
        draw_icon(ctx.canvas, icon, rect.x, rect.y)


@register("Divider")
class Divider(Widget):
    props = {
        "color": (v_color, (60, 60, 60)),
        "orientation": (v_oneof("horizontal", "vertical"), "horizontal"),
    }

    def render(self, ctx, rect, p, node):
        if p["orientation"] == "horizontal":
            for x in range(rect.x, rect.x + rect.w):
                ctx.canvas.SetPixel(x, rect.y + rect.h // 2, *p["color"])
        else:
            for y in range(rect.y, rect.y + rect.h):
                ctx.canvas.SetPixel(rect.x + rect.w // 2, y, *p["color"])


@register("TrainBadge")
class TrainBadge(Widget):
    props = {"route": (v_text, None), "color": (v_color, None), "radius": (v_int, 6)}
    required = ("route",)

    def render(self, ctx, rect, p, node):
        color = p["color"] or ROUTE_COLORS.get(p["route"], COLORS["dim"])
        draw_badge(ctx, rect, p["route"], color, p["radius"])


@register("TrainRow")
class TrainRow(Widget):
    """Route bullet, station name and next arrivals (yellow when the first is <= 2 min away)."""
    props = {"route": (v_text, None), "name": (v_text, ""), "arrivals": (v_int_list, [])}
    required = ("route",)

    def render(self, ctx, rect, p, node):
        mid = rect.y + rect.h // 2
        draw_badge(ctx, Rect(rect.x, rect.y, 16, rect.h), p["route"],
                   ROUTE_COLORS.get(p["route"], COLORS["dim"]), 6)
        draw_text(ctx, rect.x + 18, mid, p["name"], COLORS["white"], "small")
        arrivals = p["arrivals"]
        if arrivals:
            color = COLORS["yellow"] if arrivals[0] <= 2 else COLORS["white"]
            draw_text(ctx, rect.x + 18, mid + 10, format_arrivals(arrivals), color, "small")
        else:
            draw_text(ctx, rect.x + 18, mid + 10, "No data", COLORS["white"], "small")
