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
