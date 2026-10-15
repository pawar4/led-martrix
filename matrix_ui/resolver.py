"""Loads an A2UI-style screen config and renders it with the widget catalogue.

Config shape: {"root": "<id>", "components": [{"id", "component", ...props, "children": [ids]}]}.
Prop values are literals, or {"path": "/a/b"} / {"literal": v} bindings into a DataModel.
"""
import json
from datetime import datetime

from .catalog import LAYOUT_PROPS, REGISTRY, v_int
from .layout import Rect

RESERVED = {"id", "component", "children"}


class ConfigError(ValueError):
    pass


def _is_binding(value):
    return isinstance(value, dict) and len(value) == 1 and ("path" in value or "literal" in value)


class Node:
    def __init__(self, cid, widget, props, layout, child_ids):
        self.id = cid
        self.widget = widget
        self.props = props          # widget props, possibly bindings
        self.layout = layout        # width/height/x/y literals
        self.child_ids = child_ids
        self.children = []


class RenderContext:
    def __init__(self, canvas, graphics, fonts, dm, now, strict, reported):
        self.canvas = canvas
        self.graphics = graphics
        self.fonts = fonts
        self.dm = dm
        self.now = now
        self.strict = strict
        self._reported = reported

    def resolve_props(self, node):
        resolved = {}
        for name, (validator, default) in node.widget.props.items():
            value = node.props.get(name)
            if _is_binding(value):
                value = self.dm.get(value["path"]) if "path" in value else value["literal"]
            if value is None:
                resolved[name] = default
                continue
            try:
                resolved[name] = validator(value)
            except ValueError as e:
                raise ConfigError(f"{node.id}: prop '{name}': {e}")
        for name in node.widget.required:
            if resolved[name] is None:
                raise ConfigError(f"{node.id}: required prop '{name}' resolved to no value")
        return resolved

    def missing_data(self, node):
        """Names of props bound to a path that has no data yet (the source hasn't published)."""
        return {name for name, value in node.props.items()
                if _is_binding(value) and "path" in value and self.dm.get(value["path"]) is None}

    def render_node(self, node, rect):
        try:
            resolved = self.resolve_props(node)
            waiting = self.missing_data(node) & set(node.widget.loading_props)
            if waiting:
                node.widget.render_loading(self, rect, resolved, node, waiting)
            else:
                node.widget.render(self, rect, resolved, node)
        except ConfigError as e:
            if self.strict:
                raise
            if str(e) not in self._reported:   # a live display shouldn't die over one bad widget
                self._reported.add(str(e))
                print(f"matrix_ui: {e}")


class Surface:
    def __init__(self, root, sources=()):
        self.root = root
        self.sources = list(sources)    # built from the config's "sources"; not running until start_sources
        self._reported = set()      # errors already printed, so a bad widget logs once, not every frame

    @classmethod
    def load(cls, source):
        """source: path to a JSON file, or an already-parsed dict."""
        if not isinstance(source, dict):
            with open(source) as f:
                source = json.load(f)
        from .sources import build_sources      # deferred: sources imports ConfigError from here
        return cls(_build(source), build_sources(source.get("sources", [])))

    def start_sources(self, dm):
        for src in self.sources:
            src.start(dm)

    def stop_sources(self):
        for src in self.sources:
            src.stop()

    def render(self, canvas, dm, fonts, graphics, now=None, strict=False):
        ctx = RenderContext(canvas, graphics, fonts, dm, now or datetime.now, strict, self._reported)
        ctx.render_node(self.root, Rect(0, 0, canvas.width, canvas.height))


def _build(config):
    if not isinstance(config, dict) or not isinstance(config.get("root"), str):
        raise ConfigError("config needs a string 'root'")
    if not isinstance(config.get("components"), list):
        raise ConfigError("config needs a 'components' list")

    nodes = {}
    for comp in config["components"]:
        node = _build_node(comp)
        if node.id in nodes:
            raise ConfigError(f"duplicate component id '{node.id}'")
        nodes[node.id] = node

    if config["root"] not in nodes:
        raise ConfigError(f"root '{config['root']}' is not a defined component")

    parents = {}
    for node in nodes.values():
        for child_id in node.child_ids:
            if child_id not in nodes:
                raise ConfigError(f"{node.id}: child '{child_id}' is not a defined component")
            if child_id in parents:
                raise ConfigError(f"'{child_id}' has two parents ('{parents[child_id]}', '{node.id}')")
            parents[child_id] = node.id
            node.children.append(nodes[child_id])
    if config["root"] in parents:
        raise ConfigError(f"root '{config['root']}' is a child of '{parents[config['root']]}'")

    reachable, stack = set(), [nodes[config["root"]]]
    while stack:
        node = stack.pop()
        reachable.add(node.id)
        stack.extend(node.children)
    # Every non-root node has exactly one parent, so anything unreachable from root sits in a cycle or orphan group.
    unreachable = sorted(set(nodes) - reachable)
    if unreachable:
        raise ConfigError(f"components not reachable from root (orphaned or in a cycle): {unreachable}")
    return nodes[config["root"]]


def _build_node(comp):
    if not isinstance(comp, dict) or not isinstance(comp.get("id"), str):
        raise ConfigError(f"every component needs a string 'id': {comp!r}")
    cid = comp["id"]
    widget = REGISTRY.get(comp.get("component"))
    if widget is None:
        raise ConfigError(f"{cid}: unknown component {comp.get('component')!r}; available: {sorted(REGISTRY)}")

    child_ids = comp.get("children", [])
    if "children" in comp and not widget.container:
        raise ConfigError(f"{cid}: {comp['component']} cannot have children")
    if not isinstance(child_ids, list) or not all(isinstance(c, str) for c in child_ids):
        raise ConfigError(f"{cid}: 'children' must be a list of component ids")

    allowed = set(widget.props) | set(LAYOUT_PROPS) | RESERVED
    unknown = sorted(set(comp) - allowed)
    if unknown:
        raise ConfigError(f"{cid}: unknown prop(s) {unknown} for {comp['component']}; "
                          f"allowed: {sorted(allowed - RESERVED)}")
    missing = [r for r in widget.required if r not in comp]
    if missing:
        raise ConfigError(f"{cid}: missing required prop(s) {missing}")

    layout = {}
    for key in LAYOUT_PROPS:
        if key in comp:
            try:
                layout[key] = v_int(comp[key])
            except ValueError as e:
                raise ConfigError(f"{cid}: prop '{key}': {e}")

    props = {k: v for k, v in comp.items() if k in widget.props}
    for name, value in props.items():
        if not _is_binding(value):         # bound values are checked when resolved at render time
            try:
                widget.props[name][0](value)
            except ValueError as e:
                raise ConfigError(f"{cid}: prop '{name}': {e}")
    return Node(cid, widget, props, layout, child_ids)
