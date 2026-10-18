import json
import os
from datetime import datetime, timedelta

import pytest

from matrix_ui import ConfigError, DataModel, Surface
from matrix_ui.catalog import COLORS
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


class FakeTinyFont(FakeFont):
    """The real 4x6 font's metrics."""
    height = 6
    baseline = 5

    def CharacterWidth(self, c):
        return 4


TINY_FONTS = {**FONTS, "tiny": FakeTinyFont()}


def render(config, data=None, fonts=FONTS):
    surface = Surface.load(config)
    canvas, gfx = FakeCanvas(), FakeGraphics()
    surface.render(canvas, DataModel(data or {}), fonts, gfx, now=NOW, strict=True)
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
    canvas, gfx = render(cfg)       # the widget's default is "", but a text still waiting for data shows a placeholder
    assert gfx.texts == [] and canvas.pixels


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
    assert texts[1:5] == ["6am", "38F", "9am", "62F"]
    assert len(texts) == 1 + 6 * 2
    colors = {t[3]: t[2] for t in gfx.texts}          # cold is blue, hot is red, the rest yellow
    assert (colors["38F"], colors["62F"], colors["86F"]) == (COLORS["blue"], COLORS["yellow"], COLORS["red"])


def test_markets_sample_screen_renders():
    data = json.load(open(os.path.join(ROOT, "screens/markets.sample_data.json")))
    canvas, gfx = render(os.path.join(ROOT, "screens/markets.json"), data)
    texts = {t[3]: t for t in gfx.texts}
    assert texts["SPY"][2] == (255, 255, 255)
    assert texts["1M"][2] == COLORS["dim"]
    assert texts["+4.91%"][2] == (0, 220, 0)
    chart = {xy: c for xy, c in canvas.pixels.items() if xy[1] >= 17 and c == (255, 255, 255)}     # below the 8+9px header
    assert sorted({x for x, _ in chart}) == list(range(64))         # one connected line across the width


def _nfl_render(data):
    return render(os.path.join(ROOT, "screens/nfl.json"), data, TINY_FONTS)


def test_nfl_sample_screen_draws_a_card_per_game():
    data = json.load(open(os.path.join(ROOT, "screens/nfl.sample_data.json")))
    canvas, gfx = _nfl_render(data)
    texts = [t for t in gfx.texts if t[3]]
    assert [t[3] for t in texts[:2]] == ["NFL", "Oct 18"]
    at = lambda text: next(t for t in texts if t[3] == text)
    # card 0 sits at (0, 8) and is 32x27: label and clock on the status line, then a row per team
    assert [at(t)[:2] for t in ("Q4", "7:46")] == [(2, 15), (14, 15)]          # the clock is right-aligned
    assert [at(t)[:2] for t in ("HOU", "31", "JAX", "28")] == [(5, 23), (21, 24), (5, 31), (21, 32)]
    assert (at("HOU")[2], at("31")[2], at("JAX")[2], at("28")[2]) == (
        COLORS["white"], COLORS["white"], (150, 150, 150), (150, 150, 150))      # the team that is behind is grey
    assert (at("Q4")[2], at("HALF")[2], at("FINAL")[2], at("4:25 PM")[2]) == (
        COLORS["green"], COLORS["green"], (150, 150, 150), COLORS["cyan"])
    assert at("HALF")[0] == 32 + 2 + (28 - 16) // 2          # no clock: the label is centred in the second card
    assert canvas.pixels[(1, 18)] == (235, 0, 40)            # HOU's chip: its black primary falls back to the red
    assert canvas.pixels[(10, 20)] == (42, 0, 7)             # and its row is tinted with the same colour
    assert canvas.pixels[(0, 15)] == (0, 99, 0)              # live: a green border
    assert canvas.pixels[(32 + 31, 44)] == (0, 90, 90)       # not started: teal
    assert (0, 8) not in canvas.pixels                       # the corners are rounded


def test_nfl_screen_leaves_unused_cards_empty_and_shows_no_loading_placeholder():
    from datetime import date
    from matrix_ui.providers import BLANK_GAME, nfl_frame
    game = {**BLANK_GAME, "away": "HOU", "home": "JAX", "label": "FINAL", "status_color": "green"}
    canvas, _ = _nfl_render({"nfl": nfl_frame([game], date(2026, 10, 18), 16, 2, 29)})
    assert any(x < 32 and 8 <= y < 35 for x, y in canvas.pixels)                         # the first card is there
    assert not any((x >= 32 and y >= 8) or y >= 37 for x, y in canvas.pixels)            # and every other card is not
    canvas, gfx = _nfl_render({"nfl": nfl_frame([], date(2026, 10, 20), 16, 2, 29)})
    assert [t[3] for t in gfx.texts if t[3]] == ["NFL", "Oct 20", "No games"]
    assert all(y < 8 for _, y in canvas.pixels)                                            # nothing but the header band


def test_nfl_screen_shows_card_placeholders_until_the_first_fetch_and_holds_still():
    canvas, gfx = _nfl_render({})
    assert not any(t[3] for t in gfx.texts if t[0] > 0 and t[1] > 8)       # no text on the cards
    for x, y in ((0, 15), (32, 15), (0, 44), (32, 44)):                     # each card is drawn as an empty frame
        assert canvas.pixels[(x, y)] == (30, 33, 45)


def test_nfl_screen_scrolls_through_every_game_and_stops_where_the_games_end():
    data = json.load(open(os.path.join(ROOT, "screens/nfl.sample_data.json")))
    assert data["nfl"]["length"] == 5 * 29 and len(data["nfl"]["games"]) == 16     # nine games: five rows of two, 16 cards
    surface = Surface.load(os.path.join(ROOT, "screens/nfl.json"))
    dm = DataModel(data)
    t0 = datetime(2026, 10, 18, 13)

    def shown(seconds):
        canvas, gfx = FakeCanvas(), FakeGraphics()
        surface.render(canvas, dm, TINY_FONTS, gfx, now=lambda: t0 + timedelta(seconds=seconds), strict=True)
        return canvas, [t[3] for t in gfx.texts if t[3]]

    _, first = shown(0)
    assert "HOU" in first and "DAL" not in first
    assert shown(1.9)[1] == first                                   # rests at the top for `hold` seconds
    assert shown(6)[1] != first                                     # then moves
    canvas, last = shown(13.5)      # 89 pixels to go at 8 a second after 2 seconds' rest: the end is 13.1 seconds in
    assert "DAL" in last and "HOU" not in last
    assert shown(15)[1] == last                                     # it rests there for `hold` seconds too
    assert shown(15.2)[1] == first                                  # before starting over
    assert max(y for _, y in canvas.pixels) == 61                   # the last row of cards ends just above the bottom edge
    assert {c for (x, y), c in canvas.pixels.items() if y < 8} == {(0, 28, 70)}      # cards never spill into the header


# ---- scroll ----

T0 = datetime(2026, 10, 18, 13)


def render_at(surface, seconds, data=None, fonts=FONTS, graphics=None):
    """Render `surface` as it looks `seconds` after its first frame (render once at 0 to start its clock)."""
    canvas = FakeCanvas()
    gfx = graphics or FakeGraphics()
    surface.render(canvas, DataModel(data or {}), fonts, gfx, now=lambda: T0 + timedelta(seconds=seconds), strict=True)
    return canvas, gfx


def stripes(**scroll):
    """A 20-pixel window at y 10 onto 60 pixels of stripes: red for 0-19, green for 20-39 and blue for 40-59."""
    return Surface.load(screen(
        {"id": "root", "component": "Stack", "children": ["view"]},
        {"id": "view", "component": "Scroll", "y": 10, "height": 20, **scroll, "children": ["col"]},
        {"id": "col", "component": "Column", "height": 60, "children": ["a", "b", "c"]},
        {"id": "a", "component": "Fill", "color": "red"},
        {"id": "b", "component": "Fill", "color": "green"},
        {"id": "c", "component": "Fill", "color": "blue"}))


def test_scroll_offset_rests_moves_rests_and_repeats():
    from matrix_ui.catalog import scroll_offset
    at = lambda t: scroll_offset(t, 40, 10, 2)          # 40 pixels at 10 a second, 2 seconds' rest each end: 8 seconds
    assert [at(t) for t in (0, 1.9, 2, 3, 5.9, 6, 7.9)] == [0, 0, 0, 10, 39, 40, 40]
    assert [at(t) for t in (8, 11, 16)] == [0, 10, 0]   # then it starts over
    assert [scroll_offset(t, 0, 10, 2) for t in (0, 5)] == [0, 0]           # nothing to scroll
    assert scroll_offset(5, -30, 10, 2) == 0


def test_scroll_shows_a_window_of_its_child_that_moves_up_and_never_draws_outside_it():
    surface = stripes(speed=10, hold=1)
    for seconds, top, bottom in ((0, "red", "red"), (0.9, "red", "red"), (3, "green", "green"), (4, "green", "blue"),
                                 (5, "blue", "blue"), (5.9, "blue", "blue"), (6.5, "red", "red")):       # 6 seconds all told
        canvas, _ = render_at(surface, seconds)
        assert {y for _, y in canvas.pixels} == set(range(10, 30))          # only the window is painted, all of it
        assert (canvas.pixels[(0, 10)], canvas.pixels[(63, 29)]) == (COLORS[top], COLORS[bottom])


def test_scroll_length_ends_the_scroll_where_the_content_does():
    capped = stripes(speed=10, hold=1, length=40)          # the blue stripe is not worth showing
    render_at(capped, 0)
    for seconds in (2.5, 3.2, 4.5):                             # 20 pixels to go: at the end from 3 seconds, then back to the start
        assert COLORS["blue"] not in render_at(capped, seconds)[0].pixels.values()
    assert render_at(capped, 3.2)[0].pixels[(0, 29)] == COLORS["green"]
    assert render_at(capped, 4.5)[0].pixels[(0, 10)] == COLORS["red"]
    overlong = stripes(speed=10, hold=1, length=500)            # more than there is: it stops at the child's end
    render_at(overlong, 0)
    assert render_at(overlong, 5)[0].pixels[(0, 29)] == COLORS["blue"]


def test_scroll_with_a_bound_length_that_has_no_data_yet_shows_the_top_and_stays_put():
    surface = stripes(speed=10, hold=1, length={"path": "/len"})
    render_at(surface, 0)
    canvas, _ = render_at(surface, 3)
    assert (canvas.pixels[(0, 10)], canvas.pixels[(0, 29)]) == (COLORS["red"], COLORS["red"])
    canvas, _ = render_at(surface, 3, {"len": 60})              # data arrived: the clock starts now, so this is still the start
    assert canvas.pixels[(0, 29)] == COLORS["red"]
    assert render_at(surface, 5.5, {"len": 60})[0].pixels[(0, 29)] == COLORS["green"]      # 2.5 seconds on: 15 pixels up


def test_scroll_leaves_a_child_that_fits_alone():
    surface = Surface.load(screen(
        {"id": "view", "component": "Scroll", "children": ["col"]},
        {"id": "col", "component": "Column", "height": 40, "children": ["a"]},
        {"id": "a", "component": "Fill", "color": "red"}, root="view"))
    render_at(surface, 0)
    assert render_at(surface, 0)[0].pixels == render_at(surface, 9)[0].pixels
    assert {y for _, y in render_at(surface, 9)[0].pixels} == set(range(40))


def test_scroll_takes_exactly_one_child():
    with pytest.raises(ConfigError, match="at most 1 child"):
        Surface.load(screen({"id": "s", "component": "Scroll", "children": ["a", "b"]},
                            {"id": "a", "component": "Fill"}, {"id": "b", "component": "Fill"}, root="s"))
    for bad in ({"speed": 0}, {"speed": "fast"}, {"hold": -1}, {"length": 1.5}):
        with pytest.raises(ConfigError, match="prop"):
            Surface.load(screen({"id": "s", "component": "Scroll", **bad}, root="s"))


def test_nested_scrolls_clip_to_the_smaller_window():
    surface = Surface.load(screen(
        {"id": "root", "component": "Stack", "children": ["outer"]},
        {"id": "outer", "component": "Scroll", "y": 10, "height": 20, "children": ["tall"]},
        {"id": "tall", "component": "Stack", "height": 60, "children": ["inner"]},
        {"id": "inner", "component": "Scroll", "children": ["fill"]},          # its window is the whole 60 pixels
        {"id": "fill", "component": "Fill", "height": 120, "color": "red"}))
    canvas, _ = render_at(surface, 0)
    assert {y for _, y in canvas.pixels} == set(range(10, 30))


def _text_scroll():
    return Surface.load(screen(
        {"id": "root", "component": "Stack", "children": ["view"]},
        {"id": "view", "component": "Scroll", "y": 10, "height": 20, "speed": 10, "hold": 0, "children": ["tall"]},
        {"id": "tall", "component": "Stack", "height": 60, "children": ["top", "low"]},
        {"id": "top", "component": "Text", "x": 4, "height": 6, "font": "tiny", "text": "HI"},
        {"id": "low", "component": "Text", "x": 4, "y": 40, "height": 6, "font": "tiny", "text": "LO"}))


class SpyGraphics(FakeGraphics):
    def __init__(self):
        super().__init__()
        self.canvases = []

    def DrawText(self, canvas, *args):
        self.canvases.append(canvas)
        return super().DrawText(canvas, *args)


def test_text_in_a_scroll_is_drawn_natively_when_in_view_and_pixel_by_pixel_when_it_straddles_the_edge():
    surface = _text_scroll()
    render_at(surface, 0, fonts=TINY_FONTS)
    canvas, gfx = render_at(surface, 3, fonts=TINY_FONTS, graphics=SpyGraphics())      # 30 pixels up: "LO" is at y 20, in view
    assert [t[3] for t in gfx.texts] == ["LO"] and gfx.canvases == [canvas]            # native, on the real canvas
    assert canvas.pixels == {}                                                          # (the fake draws no pixels)

    canvas, gfx = render_at(surface, 0.35, fonts=TINY_FONTS, graphics=SpyGraphics())   # 3 pixels up: "HI" is cut by the top edge
    from matrix_ui.bdf import load_bdf, text_pixels
    from matrix_ui.backend import font_file
    glyphs = load_bdf(font_file("tiny"))
    assert gfx.texts == []
    assert set(canvas.pixels) == {xy for xy in text_pixels(glyphs, "HI", 4, 12) if xy[1] >= 10}      # the part below the edge
    assert len(canvas.pixels) < len(set(text_pixels(glyphs, "HI", 4, 12))) and set(canvas.pixels.values()) == {COLORS["white"]}

    canvas, gfx = render_at(surface, 1, fonts=TINY_FONTS, graphics=SpyGraphics())      # 10 pixels up: "HI" is out of view
    assert gfx.texts == [] and canvas.pixels == {}


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


# ---- loading placeholders ----

def _render_at(cfg, data, now):
    surface = Surface.load(cfg)
    canvas, gfx = FakeCanvas(), FakeGraphics()
    surface.render(canvas, DataModel(data or {}), FONTS, gfx, now=lambda: now, strict=True)
    return canvas, gfx


def test_text_without_data_shimmers_and_then_shows_the_text():
    cfg = screen({"id": "t", "component": "Text", "width": 40, "height": 8, "text": {"path": "/x"}}, root="t")
    canvas, gfx = _render_at(cfg, {}, datetime(2026, 1, 1, 9, 5, 0))
    assert gfx.texts == [] and canvas.pixels[(2, 2)][0] >= 30
    # the highlight moves: the same pixel differs half a period later
    later, _ = _render_at(cfg, {}, datetime(2026, 1, 1, 9, 5, 0, 400_000))
    assert any(canvas.pixels.get(k) != later.pixels.get(k) for k in canvas.pixels)
    _, gfx = _render_at(cfg, {"x": "hi"}, datetime(2026, 1, 1, 9, 5, 0))
    assert [t[3] for t in gfx.texts] == ["hi"]


def test_literal_text_never_shows_a_placeholder():
    canvas, gfx = _render_at(screen({"id": "t", "component": "Text", "text": ""}, root="t"), {}, datetime(2026, 1, 1))
    assert canvas.pixels == {}


def test_train_row_draws_badge_and_shimmers_missing_lines():
    cfg = screen({"id": "r", "component": "TrainRow", "route": "E", "height": 22,
                  "name": {"path": "/n"}, "arrivals": {"path": "/a"}}, root="r")
    canvas, gfx = _render_at(cfg, {}, datetime(2026, 1, 1))
    assert gfx.texts[0][3] == "E" and all(t[3] not in ("No data", "?") for t in gfx.texts)
    assert (18, 8) in canvas.pixels or any(x >= 18 for x, _ in canvas.pixels)
    _, gfx = _render_at(cfg, {"n": "Court Sq", "a": []}, datetime(2026, 1, 1))
    assert "No data" in [t[3] for t in gfx.texts]       # real, empty data still says so


def test_night_swaps_sun_for_moon():
    from matrix_ui.icons import MOON, PARTLY_CLOUDY, PARTLY_CLOUDY_NIGHT, SUN, get_icon_for_code
    assert get_icon_for_code(0) is SUN and get_icon_for_code(0, True) is SUN
    assert get_icon_for_code(0, False) is MOON
    assert get_icon_for_code(1, True) is PARTLY_CLOUDY and get_icon_for_code(1, False) is PARTLY_CLOUDY_NIGHT
    assert get_icon_for_code(61, False) is get_icon_for_code(61, True)      # rain looks the same at night


def test_icon_is_day_binding_picks_moon():
    from matrix_ui.icons import MOON, SUN
    cfg = screen({"id": "i", "component": "Icon", "weather_code": {"path": "/c"}, "is_day": {"path": "/d"}}, root="i")

    def drawn(data):
        canvas, _ = _render_at(cfg, data, datetime(2026, 1, 1))
        return {xy for xy, _ in canvas.pixels.items()}
    cells = lambda icon: {(x, y) for y, row in enumerate(icon) for x, c in enumerate(row) if c}
    assert drawn({"c": 0, "d": False}) == cells(MOON)
    assert drawn({"c": 0, "d": True}) == cells(SUN)
    assert drawn({"c": 0}) == cells(SUN)             # no is_day yet: assume day


def test_weather_icon_waits_for_data():
    cfg = screen({"id": "i", "component": "Icon", "weather_code": {"path": "/c"}}, root="i")
    canvas, _ = _render_at(cfg, {}, datetime(2026, 1, 1))
    assert canvas.pixels and all(v[0] == v[1] == v[2] for v in canvas.pixels.values())     # grey, not the ? glyph
