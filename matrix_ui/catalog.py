"""Widget catalogue: every component a screen config may use.

A widget declares its props as {name: (validator, default)}. Validators return the
(normalised) value or raise ValueError. Add a widget by subclassing Widget and
decorating it with @register("Name").
"""
from datetime import datetime

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
    "orange": (255, 120, 0),
    "blue": (40, 100, 255),
    "purple": (160, 60, 255),
    "magenta": (255, 0, 160),
    "pink": (255, 130, 180),
    "lime": (140, 255, 0),
    "teal": (0, 160, 130),
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


def v_number(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"expected number, got {v!r}")
    return v


def v_number_list(v):
    if not isinstance(v, list) or not all(isinstance(i, (int, float)) and not isinstance(i, bool) for i in v):
        raise ValueError(f"expected list of numbers, got {v!r}")
    return v


def v_datetime(v):
    """ISO 8601 date-time string ('2026-12-26T11:00:00'); naive means the machine's local time."""
    if not isinstance(v, str):
        raise ValueError(f"expected an ISO date-time string, got {v!r}")
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        raise ValueError(f"expected an ISO date-time like '2026-12-26T11:00:00', got {v!r}") from None


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


def fit_text(font, text, max_width):
    """Longest prefix of `text` that fits in `max_width` pixels."""
    while text and text_width(font, text) > max_width:
        text = text[:-1]
    return text


def draw_text(ctx, x, baseline_y, text, color, font_name):
    font = ctx.fonts[font_name]
    ctx.graphics.DrawText(ctx.canvas, font, x, baseline_y, ctx.graphics.Color(*color), text)


def draw_aligned_text(ctx, rect, text, color, font_name, align):
    font = ctx.fonts[font_name]
    text = fit_text(font, text, rect.w)
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
    # 6x10 glyphs are ~5px wide in a 6px cell and 7px tall (rows baseline-7..baseline-1)
    draw_text(ctx, cx - (text_width(font, route) - 1) // 2, cy + 4,
              route, COLORS["white"], "large")


def wrap_text(font, text, width):
    """Greedy word wrap to `width` pixels; a word wider than the box is split across lines."""
    lines, line = [], ""
    for word in text.split():
        while text_width(font, word) > width:
            if line:
                lines.append(line)
                line = ""
            head = fit_text(font, word, width)
            if not head:            # not even one glyph fits
                return lines
            lines.append(head)
            word = word[len(head):]
        if not word:
            continue
        if not line:
            line = word
        elif text_width(font, line + " " + word) <= width:
            line += " " + word
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def format_arrivals(minutes, font=None, max_width=None):
    """Join arrival times, dropping trailing ones until the line fits `max_width`."""
    minutes = list(minutes)
    while True:
        text = ", ".join("Now" if m == 0 else f"{m}m" for m in minutes)
        if font is None or len(minutes) <= 1 or text_width(font, text) <= max_width:
            return text
        minutes.pop()


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


def draw_arrow(canvas, x, y, up, color):
    """5px wide, 3px tall triangle with its top-left corner at (x, y)."""
    for row in range(3):
        half = row if up else 2 - row
        for dx in range(2 - half, 3 + half):
            canvas.SetPixel(x + dx, y + row, *color)


@register("TrainRow")
class TrainRow(Widget):
    """Route bullet, station name and next arrivals (yellow when the first is <= 2 min away).
    `direction` (N or S) draws an up arrow above the badge or a down arrow below it. `alert` is a colour
    drawn as a 3px status dot just off the badge's top-right; green (all clear) draws nothing."""
    props = {"route": (v_text, None), "name": (v_text, ""), "arrivals": (v_int_list, []),
             "direction": (v_oneof("N", "S", ""), ""), "alert": (v_color, None)}
    required = ("route",)

    def render(self, ctx, rect, p, node):
        mid = rect.y + rect.h // 2
        draw_badge(ctx, Rect(rect.x, rect.y, 16, rect.h), p["route"],
                   ROUTE_COLORS.get(p["route"], COLORS["dim"]), 6)
        font = ctx.fonts["small"]
        text_w = rect.w - 18
        draw_text(ctx, rect.x + 18, mid, fit_text(font, p["name"], text_w), COLORS["white"], "small")
        if p["alert"] not in (None, COLORS["green"]):
            for dx in range(3):
                for dy in range(3):
                    ctx.canvas.SetPixel(rect.x + 13 + dx, mid - 8 + dy, *p["alert"])
        if p["direction"]:      # the badge is 13px tall: the arrow sits in the gap on the side it points to
            up = p["direction"] == "N"
            draw_arrow(ctx.canvas, rect.x + 6, mid - 10 if up else mid + 8, up, COLORS["cyan"])
        arrivals = p["arrivals"]
        if arrivals:
            color = COLORS["yellow"] if arrivals[0] <= 2 else COLORS["white"]
            line = fit_text(font, format_arrivals(arrivals, font, text_w), text_w)
        else:
            color, line = COLORS["white"], "No data"
        draw_text(ctx, rect.x + 18, mid + 10, line, color, "small")


@register("ForecastSlot")
class ForecastSlot(Widget):
    """One forecast step: weather icon, hour label (tiny) and temperature. Fits a 32x14 box or taller."""
    props = {"hour": (v_text, ""), "weather_code": (v_int, None), "temp": (v_text, ""),
             "hour_color": (v_color, COLORS["dim"]), "temp_color": (v_color, COLORS["white"])}

    def render(self, ctx, rect, p, node):
        icon = get_icon_for_code(p["weather_code"]) if p["weather_code"] is not None else UNKNOWN
        draw_icon(ctx.canvas, icon, rect.x, rect.y + (rect.h - 10) // 2)
        top = rect.y + max((rect.h - 14) // 2, 0)        # hour (6px) + temperature (8px), centred
        text_rect = Rect(rect.x + 12, top, max(rect.w - 12, 0), 14)
        draw_aligned_text(ctx, text_rect, p["hour"], p["hour_color"], "tiny", "left")
        draw_aligned_text(ctx, Rect(text_rect.x, top + 6, text_rect.w, 8),
                          p["temp"], p["temp_color"], "small", "left")


@register("LineChart")
class LineChart(Widget):
    """Line chart of `values` stretched to the box width and scaled to its height (min to max).
    `fill` shades the area under the line. `baseline` (e.g. the previous close) is drawn as a dashed
    line and included in the scale."""
    props = {"values": (v_number_list, []), "color": (v_color, COLORS["green"]), "fill": (v_color, None),
             "baseline": (v_number, None), "baseline_color": (v_color, (60, 60, 60))}

    def render(self, ctx, rect, p, node):
        values, baseline = p["values"], p["baseline"]
        if not values or rect.w < 1 or rect.h < 1:
            return
        scale = values + ([baseline] if baseline is not None else [])
        lo, hi = min(scale), max(scale)

        def row(v):         # bottom row is the minimum; a flat series sits in the middle
            if hi == lo:
                return rect.y + (rect.h - 1) // 2
            return rect.y + rect.h - 1 - round((v - lo) / (hi - lo) * (rect.h - 1))

        ys = []
        for i in range(rect.w):
            pos = i * (len(values) - 1) / (rect.w - 1) if rect.w > 1 else 0
            j = int(pos)
            ys.append(row(values[j] + (values[min(j + 1, len(values) - 1)] - values[j]) * (pos - j)))
        if p["fill"] is not None:
            for i, y in enumerate(ys):
                for yy in range(y + 1, rect.y + rect.h):
                    ctx.canvas.SetPixel(rect.x + i, yy, *p["fill"])
        if baseline is not None:
            for x in range(rect.x, rect.x + rect.w):
                if (x - rect.x) % 4 < 2:
                    ctx.canvas.SetPixel(x, row(baseline), *p["baseline_color"])
        prev = None
        for i, y in enumerate(ys):
            # Join to the previous column so steep moves stay a connected line.
            for yy in range(min(y, prev if prev is not None else y), max(y, prev if prev is not None else y) + 1):
                ctx.canvas.SetPixel(rect.x + i, yy, *p["color"])
            prev = y


@register("Fill")
class Fill(Widget):
    """Solid rectangle; put it first in a `Stack` for a background."""
    props = {"color": (v_color, COLORS["black"])}

    def render(self, ctx, rect, p, node):
        for y in range(rect.y, rect.y + rect.h):
            for x in range(rect.x, rect.x + rect.w):
                ctx.canvas.SetPixel(x, y, *p["color"])


@register("ProgressBar")
class ProgressBar(Widget):
    """Horizontal bar filled left to right by `value` (0 to 1), drawn over an optional `track` colour."""
    props = {"value": (v_number, 0), "color": (v_color, COLORS["green"]), "track": (v_color, None)}

    def render(self, ctx, rect, p, node):
        filled = round(min(max(p["value"], 0), 1) * rect.w)
        for y in range(rect.y, rect.y + rect.h):
            for x in range(rect.x, rect.x + rect.w):
                color = p["color"] if x - rect.x < filled else p["track"]
                if color is not None:
                    ctx.canvas.SetPixel(x, y, *color)


@register("WrapText")
class WrapText(Widget):
    """Text word-wrapped to its box, top-aligned, one line per `font.height + line_gap`. Text taller than
    the box scrolls a whole line at a time: `scroll` (0 to 1) picks the window, 0 showing the first lines
    and 1 the last. Bind it to a value that moves over time; with text that fits it does nothing."""
    props = {
        "text": (v_text, ""),
        "color": (v_color, COLORS["white"]),
        "font": (v_oneof(*FONT_NAMES), "small"),
        "align": (v_oneof("left", "center", "right"), "left"),
        "line_gap": (v_int, 1),
        "scroll": (v_number, 0),
    }

    def render(self, ctx, rect, p, node):
        font = ctx.fonts[p["font"]]
        pitch = font.height + p["line_gap"]
        lines = wrap_text(font, p["text"], rect.w)
        visible = (rect.h - font.height) // pitch + 1 if rect.h >= font.height else 0
        first = round(min(max(p["scroll"], 0), 1) * max(len(lines) - visible, 0))
        for i, line in enumerate(lines[first:first + visible]):
            draw_aligned_text(ctx, Rect(rect.x, rect.y + i * pitch, rect.w, font.height),
                              line, p["color"], p["font"], p["align"])


def time_left(target, now):
    """Whole (days, hours, minutes, seconds) from `now` until `target`, all zero once it has passed."""
    if target.tzinfo is not None:
        now = now.astimezone()
    remaining = max(int((target - now).total_seconds()), 0)
    days, rest = divmod(remaining, 86400)
    hours, rest = divmod(rest, 3600)
    return days, hours, *divmod(rest, 60)


@register("Countdown")
class Countdown(Widget):
    """Time left until `target`, formatted with `{d}` days, `{h}` hours, `{m}` minutes and `{s}` seconds
    (each takes a format spec, e.g. `{h:02}`). Reads the clock like `Clock`, so it needs no data source.
    Shows zeros once `target` has passed."""
    props = {
        "target": (v_datetime, None),
        "format": (v_text, "{d}d {h:02}:{m:02}:{s:02}"),
        "color": (v_color, COLORS["white"]),
        "font": (v_oneof(*FONT_NAMES), "small"),
        "align": (v_oneof("left", "center", "right"), "left"),
    }
    required = ("target",)

    def render(self, ctx, rect, p, node):
        d, h, m, s = time_left(p["target"], ctx.now())
        try:
            text = p["format"].format(d=d, h=h, m=m, s=s)
        except (KeyError, IndexError, ValueError) as e:
            from .resolver import ConfigError      # deferred: resolver imports this module
            raise ConfigError(f"{node.id}: prop 'format': {e!r}") from None
        draw_aligned_text(ctx, rect, text, p["color"], p["font"], p["align"])


@register("SpeechBubble")
class SpeechBubble(Widget):
    """Filled, outlined box with rounded corners and a two-pixel tail pointing down-left, like the old
    Bondi page. The tail sits just below the box, so leave two rows free under it."""
    props = {"fill": (v_color, (10, 10, 10)), "border": (v_color, (200, 200, 200)), "tail": (v_oneof(True, False), True)}

    def render(self, ctx, rect, p, node):
        if rect.w < 3 or rect.h < 3:
            return
        for y in range(rect.y, rect.y + rect.h):
            for x in range(rect.x, rect.x + rect.w):
                edge_x = x in (rect.x, rect.x + rect.w - 1)
                edge_y = y in (rect.y, rect.y + rect.h - 1)
                if edge_x and edge_y:
                    continue                    # rounded corner
                ctx.canvas.SetPixel(x, y, *(p["border"] if edge_x or edge_y else p["fill"]))
        if p["tail"]:
            ctx.canvas.SetPixel(rect.x + 4, rect.y + rect.h, *p["border"])
            ctx.canvas.SetPixel(rect.x + 3, rect.y + rect.h + 1, *p["border"])


_IMAGE_CACHE = {}


def load_image_pixels(path, width, height):
    """RGB rows of the image at `path` scaled to fit width x height, or None if it can't be read.
    Cached, since a screen redraws every frame."""
    key = (path, width, height)
    if key not in _IMAGE_CACHE:
        try:
            from PIL import Image as PILImage
            img = PILImage.open(path)
            img.thumbnail((width, height), PILImage.LANCZOS)
            img = img.convert("RGB")
            _IMAGE_CACHE[key] = [[img.getpixel((x, y)) for x in range(img.width)] for y in range(img.height)]
        except Exception as e:      # missing file, not an image, PIL not installed
            print(f"matrix_ui: could not load image {path!r}: {e}")
            _IMAGE_CACHE[key] = None
    return _IMAGE_CACHE[key]


@register("Image")
class Image(Widget):
    """A picture (PNG, JPEG, ...) scaled down to fit its box, keeping its aspect ratio, centred. `path` is
    relative to where you run from. A missing or unreadable file draws nothing and is reported once."""
    props = {"path": (v_text, None)}
    required = ("path",)

    def render(self, ctx, rect, p, node):
        pixels = load_image_pixels(p["path"], rect.w, rect.h)
        if not pixels:
            return
        x0 = rect.x + (rect.w - len(pixels[0])) // 2
        y0 = rect.y + (rect.h - len(pixels)) // 2
        for y, row in enumerate(pixels):
            for x, (r, g, b) in enumerate(row):
                ctx.canvas.SetPixel(x0 + x, y0 + y, r, g, b)
