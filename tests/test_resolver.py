import json
import os
from datetime import datetime

import pytest

from matrix_ui import ConfigError, DataModel, Surface
from matrix_ui.layout import Rect, split

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeCanvas:
    width = height = 64

    def __init__(self):
        self.pixels = {}

    def SetPixel(self, x, y, r, g, b):
        self.pixels[(x, y)] = (r, g, b)


class FakeFont:
    height = 8
    baseline = 7

    def CharacterWidth(self, c):
        return 5


class FakeGraphics:
    class Color:
        def __init__(self, r, g, b):
            self.rgb = (r, g, b)

    def __init__(self):
        self.texts = []

    def DrawText(self, canvas, font, x, y, color, text):
        self.texts.append((x, y, color.rgb, text))
        return len(text) * 5


FONTS = {n: FakeFont() for n in ("tiny", "small", "large")}
NOW = lambda: datetime(2026, 1, 1, 9, 5)


def render(config, data=None):
    surface = Surface.load(config)
    canvas, gfx = FakeCanvas(), FakeGraphics()
    surface.render(canvas, DataModel(data or {}), FONTS, gfx, now=NOW, strict=True)
    return canvas, gfx


def screen(*components, root="root"):
    return {"root": root, "components": list(components)}


# ---- validation ----

def test_unknown_component():
    with pytest.raises(ConfigError, match="a: unknown component 'Nope'"):
        Surface.load(screen({"id": "a", "component": "Nope"}, root="a"))


def test_unknown_prop_names_component_and_lists_allowed():
    with pytest.raises(ConfigError, match=r"t: unknown prop\(s\) \['colour'\].*allowed"):
        Surface.load(screen({"id": "t", "component": "Text", "colour": "red"}, root="t"))


def test_bad_literal_value():
    with pytest.raises(ConfigError, match="t: prop 'color'"):
        Surface.load(screen({"id": "t", "component": "Text", "color": "chartreuse"}, root="t"))


def test_missing_required_prop():
    with pytest.raises(ConfigError, match="missing required"):
        Surface.load(screen({"id": "b", "component": "TrainBadge"}, root="b"))


def test_missing_child_duplicate_id_and_bad_root():
    with pytest.raises(ConfigError, match="child 'ghost'"):
        Surface.load(screen({"id": "c", "component": "Column", "children": ["ghost"]}, root="c"))
    with pytest.raises(ConfigError, match="duplicate"):
        Surface.load(screen({"id": "a", "component": "Text"}, {"id": "a", "component": "Text"}, root="a"))
    with pytest.raises(ConfigError, match="root 'zzz'"):
        Surface.load(screen({"id": "a", "component": "Text"}, root="zzz"))


def test_cycle_and_orphan_rejected():
    cyc = screen({"id": "r", "component": "Column", "children": ["a"]},
                 {"id": "a", "component": "Column", "children": ["b"]},
                 {"id": "b", "component": "Column", "children": ["a"]}, root="r")
    with pytest.raises(ConfigError, match="two parents|not reachable"):
        Surface.load(cyc)
    orphan = screen({"id": "r", "component": "Text"}, {"id": "lost", "component": "Text"}, root="r")
    with pytest.raises(ConfigError, match=r"not reachable.*lost"):
        Surface.load(orphan)


def test_leaf_cannot_have_children():
    with pytest.raises(ConfigError, match="cannot have children"):
        Surface.load(screen({"id": "t", "component": "Text", "children": []}, root="t"))


# ---- bindings ----

def test_path_and_literal_bindings():
    cfg = screen({"id": "t", "component": "Text", "text": {"path": "/a/0/b"}}, root="t")
    _, gfx = render(cfg, {"a": [{"b": "hi"}]})
    assert gfx.texts[0][3] == "hi"
    cfg = screen({"id": "t", "component": "Text", "text": {"literal": "lit"}}, root="t")
    assert render(cfg)[1].texts[0][3] == "lit"


def test_missing_path_falls_back_to_default():
    cfg = screen({"id": "t", "component": "Text", "text": {"path": "/nope"}}, root="t")
    assert render(cfg)[1].texts[0][3] == ""


def test_bound_value_failing_validation_raises_strict_but_not_live(capsys):
    cfg = screen({"id": "t", "component": "Text", "color": {"path": "/c"}}, root="t")
    with pytest.raises(ConfigError, match="t: prop 'color'"):
        render(cfg, {"c": "chartreuse"})
    # non-strict (live display): the widget is skipped and the problem printed once
    surface = Surface.load(cfg)
    for _ in range(2):
        surface.render(FakeCanvas(), DataModel({"c": "chartreuse"}), FONTS, FakeGraphics())
    assert capsys.readouterr().out.count("prop 'color'") == 1


def test_datamodel_set_creates_path():
    dm = DataModel()
    dm.set("/x/y", 3)
    assert dm.get("/x/y") == 3 and dm.get("/x/z", "d") == "d"


# ---- layout ----

def test_split_fixed_and_flex():
    rects = split(Rect(0, 0, 64, 64), "y", [13, None, None])
    assert rects == [Rect(0, 0, 64, 13), Rect(0, 13, 64, 25), Rect(0, 38, 64, 26)]


def test_split_gap_and_padding():
    rects = split(Rect(0, 0, 64, 20), "x", [10, None], gap=2, padding=(1, 0, 0, 2))
    assert rects == [Rect(2, 1, 10, 19), Rect(14, 1, 50, 19)]


def test_row_places_children_by_width():
    cfg = screen({"id": "r", "component": "Row", "children": ["a", "b"]},
                 {"id": "a", "component": "Text", "width": 20, "text": "A"},
                 {"id": "b", "component": "Text", "text": "B"}, root="r")
    _, gfx = render(cfg)
    assert [(t[0], t[3]) for t in gfx.texts] == [(0, "A"), (20, "B")]


def test_stack_offsets_and_text_align():
    cfg = screen({"id": "s", "component": "Stack", "children": ["a"]},
                 {"id": "a", "component": "Text", "x": 4, "y": 10, "width": 30, "height": 8,
                  "text": "ab", "align": "right"}, root="s")
    _, gfx = render(cfg)
    assert gfx.texts[0][:2] == (4 + 30 - 10, 10 + 7)


# ---- sample screen ----

def test_subway_sample_screen_renders():
    data = json.load(open(os.path.join(ROOT, "screens/subway.sample_data.json")))
    canvas, gfx = render(os.path.join(ROOT, "screens/subway.json"), data)
    texts = {t[3]: t for t in gfx.texts}
    assert texts["72F"][:2] == (14, 8)
    assert texts["09:05"][0] == 34
    assert texts["Court Sq"][:2] == (18, 24)
    assert texts["11m, 17m"][:3] == (18, 34, (255, 255, 255))   # 3rd arrival dropped: no room
    assert texts["2m, 14m"][2] == (255, 220, 0)      # first arrival <= 2 min
    assert canvas.pixels[(8, 24)] == (0, 57, 166) or canvas.pixels[(9, 24)] == (0, 57, 166)  # E bullet
    assert canvas.pixels[(8, 40)] == (185, 51, 173)                                          # 7 bullet


def test_long_text_is_truncated_to_its_rect():
    cfg = screen({"id": "r", "component": "Row", "children": ["t"]},
                 {"id": "t", "component": "Text", "width": 20, "text": "abcdefgh"}, root="r")
    assert render(cfg)[1].texts[0][3] == "abcd"


def test_weather_sample_screen_renders():
    data = json.load(open(os.path.join(ROOT, "screens/weather.sample_data.json")))
    _, gfx = render(os.path.join(ROOT, "screens/weather.json"), data)
    texts = [t[3] for t in gfx.texts]
    assert texts[0] == "Sat Oct 17"
    assert texts[1:5] == ["6am", "56F", "9am", "62F"]
    assert len(texts) == 1 + 6 * 2


def test_markets_sample_screen_renders():
    data = json.load(open(os.path.join(ROOT, "screens/markets.sample_data.json")))
    canvas, gfx = render(os.path.join(ROOT, "screens/markets.json"), data)
    texts = {t[3]: t for t in gfx.texts}
    assert texts["SPY"][2] == (255, 255, 255)
    assert texts["+0.60%"][2] == (0, 220, 0)
    chart = {xy: c for xy, c in canvas.pixels.items() if xy[1] >= 20 and c == (255, 255, 255)}
    assert sorted({x for x, _ in chart}) == list(range(64))         # one connected line across the width


def test_line_chart_scales_min_to_bottom_and_max_to_top():
    cfg = screen({"id": "c", "component": "LineChart", "values": [1, 3, 2], "color": "red"}, root="c")
    pixels = render(cfg)[0].pixels
    assert pixels[(0, 63)] == (220, 0, 0)       # min at the bottom-left
    assert {x for x, y in pixels if y <= 1} <= set(range(28, 36))      # the peak, near the top-middle
    assert min(y for _, y in pixels) <= 1
    assert render(screen({"id": "c", "component": "LineChart"}, root="c"))[0].pixels == {}


def test_line_chart_baseline_is_dotted_and_scaled():
    cfg = screen({"id": "c", "component": "LineChart", "values": [2, 3], "baseline": 1}, root="c")
    pixels = render(cfg)[0].pixels
    assert pixels[(0, 63)] == pixels[(1, 63)] == (60, 60, 60)       # baseline is the minimum, on the bottom row
    assert (2, 63) not in pixels                                     # ... and dashed


def test_line_chart_fill_shades_below_the_line_only():
    cfg = screen({"id": "c", "component": "LineChart", "values": [1, 3], "color": "red", "fill": [0, 0, 90]}, root="c")
    pixels = render(cfg)[0].pixels
    assert pixels[(63, 0)] == (220, 0, 0) and pixels[(63, 63)] == (0, 0, 90)    # line on top, fill under it
    assert (63, 0) in pixels and not any(c == (0, 0, 90) for xy, c in pixels.items() if xy[1] <= 0)

# ---- trivia widgets ----

def boxed(widget):
    """A screen with `widget` at the top-left of the canvas, sized by its own width/height."""
    return screen({"id": "root", "component": "Stack", "children": [widget["id"]]}, widget)


def test_wrap_text_breaks_on_words_and_splits_long_ones():
    from matrix_ui.catalog import wrap_text
    font = FakeFont()           # 5px per character
    assert wrap_text(font, "ONE TWO THREE", 50) == ["ONE TWO", "THREE"]
    assert wrap_text(font, "ABCDEFGHIJKL MN", 25) == ["ABCDE", "FGHIJ", "KL MN"]
    assert wrap_text(font, "", 50) == []
    assert wrap_text(font, "WIDE", 4) == []         # not even one glyph fits


def test_wrap_text_widget_drops_lines_that_do_not_fit():
    _, gfx = render(boxed({"id": "w", "component": "WrapText", "text": "AAAA BBBB CCCC DDDD",
                           "width": 20, "height": 20, "font": "small", "line_gap": 2}))
    assert [t[3] for t in gfx.texts] == ["AAAA", "BBBB"]         # 8px lines every 10px: two fit in 20px
    assert [t[1] for t in gfx.texts] == [7, 17]


def test_wrap_text_scroll_moves_a_window_of_whole_lines():
    def shown(scroll):
        _, gfx = render(boxed({"id": "w", "component": "WrapText", "text": "A B C D E", "width": 5,
                               "height": 20, "font": "small", "line_gap": 2, "scroll": scroll}))
        return [t[3] for t in gfx.texts]
    assert shown(0) == ["A", "B"]           # five one-letter lines, two visible
    assert shown(0.5) == ["C", "D"]
    assert shown(1) == ["D", "E"]
    assert shown(7) == ["D", "E"] and shown(-1) == ["A", "B"]


def test_progress_bar_fills_proportionally_and_clamps():
    def filled(value):
        canvas, _ = render(boxed({"id": "w", "component": "ProgressBar", "width": 20, "height": 2,
                                  "value": value, "color": "red"}))
        return {x for (x, y), c in canvas.pixels.items() if c == (220, 0, 0) and y == 0}
    assert filled(0.5) == set(range(10))
    assert filled(2) == set(range(20))
    assert filled(-1) == set()


def test_fill_paints_the_box():
    canvas, _ = render(boxed({"id": "w", "component": "Fill", "width": 3, "height": 2, "color": [1, 2, 3]}))
    assert canvas.pixels == {(x, y): (1, 2, 3) for x in range(3) for y in range(2)}


def test_trivia_screen_renders_sample_data():
    with open(os.path.join(ROOT, "screens", "trivia.sample_data.json")) as f:
        data = json.load(f)
    _, gfx = render(os.path.join(ROOT, "screens", "trivia.json"), data)
    texts = [t[3] for t in gfx.texts if t[3]]
    assert texts[:3] == ["GEOGRAPHY", "$600", "3/5"]
    assert "".join(texts[3:]).replace(" ", "") == "THESMALLESTCOUNTRYINTHEWORLD"


# ---- countdown, speech bubble, image ----

def countdown(target, **props):
    return screen({"id": "c", "component": "Countdown", "target": target, **props}, root="c")


def test_countdown_splits_days_hours_minutes_seconds():
    # NOW is 2026-01-01 09:05:00; 3 days, 2 hours, 4 minutes, 5 seconds later
    _, gfx = render(countdown("2026-01-04T11:09:05", format="{d}d {h:02}:{m:02}:{s:02}"))
    assert gfx.texts[0][3] == "3d 02:04:05"


def test_countdown_clamps_to_zero_after_target():
    _, gfx = render(countdown("2025-12-31T00:00:00"))
    assert gfx.texts[0][3] == "0d 00:00:00"


def test_countdown_target_can_be_bound():
    _, gfx = render(screen({"id": "c", "component": "Countdown", "target": {"path": "/t"}}, root="c"),
                    {"t": "2026-01-01T09:06:00"})
    assert gfx.texts[0][3] == "0d 00:01:00"


def test_countdown_rejects_a_bad_target_and_a_bad_format():
    with pytest.raises(ConfigError, match="c: prop 'target'"):
        Surface.load(countdown("next tuesday"))
    with pytest.raises(ConfigError, match="c: prop 'format'"):
        render(countdown("2026-01-02T00:00:00", format="{weeks}"))


def test_speech_bubble_has_rounded_corners_fill_and_tail():
    canvas, _ = render(screen({"id": "s", "component": "Stack", "children": ["b"]},
                              {"id": "b", "component": "SpeechBubble", "width": 10, "height": 6,
                               "fill": [1, 1, 1], "border": [9, 9, 9]}, root="s"))
    assert (0, 0) not in canvas.pixels and (9, 5) not in canvas.pixels
    assert canvas.pixels[(1, 0)] == (9, 9, 9) and canvas.pixels[(0, 1)] == (9, 9, 9)
    assert canvas.pixels[(5, 3)] == (1, 1, 1)
    assert canvas.pixels[(4, 6)] == (9, 9, 9) and canvas.pixels[(3, 7)] == (9, 9, 9)


def test_image_scales_to_fit_and_centres(tmp_path):
    from PIL import Image as PILImage
    path = tmp_path / "wide.png"
    PILImage.new("RGB", (128, 64), (255, 0, 0)).save(path)
    canvas, _ = render(screen({"id": "i", "component": "Image", "path": str(path)}, root="i"))
    assert canvas.pixels[(0, 16)] == (255, 0, 0) and canvas.pixels[(63, 47)] == (255, 0, 0)
    assert (0, 15) not in canvas.pixels and (0, 48) not in canvas.pixels


def test_image_missing_file_draws_nothing():
    canvas, _ = render(screen({"id": "i", "component": "Image", "path": "no/such/file.png"}, root="i"))
    assert canvas.pixels == {}


def test_weather_sample_has_a_daylight_bar():
    data = json.load(open(os.path.join(ROOT, "screens/weather.sample_data.json")))
    canvas, _ = render(os.path.join(ROOT, "screens/weather.json"), data)
    assert canvas.pixels[(0, 0)] == canvas.pixels[(38, 1)] == (255, 220, 0)      # 62% of 64px filled
    assert canvas.pixels[(60, 0)] == (25, 25, 25)


def test_train_row_alert_dot():
    def dot(color):
        cfg = screen({"id": "r", "component": "TrainRow", "route": "E", "alert": color}, root="r")
        return render(cfg)[0].pixels.get((14, 25))
    assert dot("orange") == (255, 120, 0)
    assert dot("green") is None
