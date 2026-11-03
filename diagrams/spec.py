"""Diagram specs (v1): what make_diagram and check_diagram accept.

A spec names its kind ("graph", "geometry", "circuit", "apparatus",
"ray"), a non-empty title, and its elements. Unknown keys are refused at
every level, so a typo fails here instead of silently drawing nothing.
Coordinates are abstract units; the renderer maps them onto the canvas.
"""

from __future__ import annotations

KINDS = ("graph", "geometry", "circuit", "apparatus", "ray")
COMPONENTS = ("battery", "bulb", "resistor", "switch")
APPARATUS = ("beaker", "flask", "test_tube", "burner")
OPTICS = ("mirror", "lens")
SHAPES = ("triangle", "rectangle", "circle", "line")
TOP_KEYS = {
    "kind",
    "title",
    "caption",
    "x",
    "y",
    "grid",
    "points",
    "segments",
    "shapes",
    "wires",
    "components",
    "rays",
    "optics",
}
ELEMENT_KEYS = {"points", "segments", "shapes", "wires", "components", "rays", "optics"}
MAX_LABEL = 24
MAX_COORD = 1000


def _is_num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _point(value, where: str, problems: list) -> None:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or not all(_is_num(v) for v in value)
    ):
        problems.append(f"{where} must be [x, y] numbers")
        return
    if any(abs(v) > MAX_COORD for v in value):
        problems.append(f"{where} is out of range (+/-{MAX_COORD})")


def _label(value, where: str, problems: list) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{where} label must be a non-empty string")
    elif len(value) > MAX_LABEL:
        problems.append(f"{where} label is longer than {MAX_LABEL} characters")


def _strict(keys: set, allowed: set, where: str, problems: list) -> None:
    for key in sorted(keys - allowed):
        problems.append(f"{where} has unknown key {key!r}")


def validate_spec(spec: dict) -> list:
    """Every problem with a diagram spec (empty = valid)."""
    if not isinstance(spec, dict):
        return ["spec must be an object"]
    problems = []
    _strict(set(spec), TOP_KEYS, "spec", problems)
    kind = spec.get("kind")
    if kind not in KINDS:
        return problems + [f"kind must be one of {', '.join(KINDS)}"]
    if not isinstance(spec.get("title"), str) or not spec["title"].strip():
        problems.append("title must be a non-empty string")
    if "caption" in spec and not isinstance(spec["caption"], str):
        problems.append("caption must be a string")
    if kind == "graph":
        _graph(spec, problems)
    elif kind == "geometry":
        _geometry(spec, problems)
    elif kind == "circuit":
        _circuit(spec, problems)
    elif kind == "apparatus":
        _apparatus(spec, problems)
    else:
        _ray(spec, problems)
    return problems


def _axis(spec: dict, name: str, problems: list) -> None:
    axis = spec.get(name)
    if not isinstance(axis, dict):
        problems.append(f"{name} must be an object with min and max")
        return
    _strict(set(axis), {"min", "max", "label"}, name, problems)
    lo, hi = axis.get("min"), axis.get("max")
    if not _is_num(lo) or not _is_num(hi):
        problems.append(f"{name}.min and {name}.max must be numbers")
    elif lo >= hi:
        problems.append(f"{name}.min must be below {name}.max")
    _label(axis.get("label"), name, problems)


def _graph(spec: dict, problems: list) -> None:
    _strict(set(spec) & ELEMENT_KEYS,
           {"points", "segments"}, "graph spec", problems)
    _axis(spec, "x", problems)
    _axis(spec, "y", problems)
    if "grid" in spec and not isinstance(spec["grid"], bool):
        problems.append("grid must be true or false")
    points = spec.get("points", [])
    segments = spec.get("segments", [])
    if not isinstance(points, list) or not isinstance(segments, list):
        problems.append("points and segments must be lists")
        return
    if not points and not segments:
        problems.append("graph needs at least one point or segment")
    xaxis, yaxis = spec.get("x") or {}, spec.get("y") or {}
    for n, point in enumerate(points, start=1):
        if not isinstance(point, dict):
            problems.append(f"point {n} must be an object")
            continue
        _strict(set(point), {"x", "y", "label"}, f"point {n}", problems)
        if not _is_num(point.get("x")) or not _is_num(point.get("y")):
            problems.append(f"point {n} needs numeric x and y")
            continue
        _label(point.get("label"), f"point {n}", problems)
        for axis, value in (("x", point["x"]), ("y", point["y"])):
            bounds = spec.get(axis) or {}
            if _is_num(bounds.get("min")) and _is_num(bounds.get("max")) and not (
                bounds["min"] <= value <= bounds["max"]
            ):
                problems.append(f"point {n} {axis}={value} is outside the {axis} range")
    for n, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            problems.append(f"segment {n} must be an object")
            continue
        _strict(set(segment), {"a", "b"}, f"segment {n}", problems)
        _point(segment.get("a"), f"segment {n} a", problems)
        _point(segment.get("b"), f"segment {n} b", problems)


def _geometry(spec: dict, problems: list) -> None:
    _strict(set(spec) & ELEMENT_KEYS,
           {"shapes"}, "geometry spec", problems)
    shapes = spec.get("shapes")
    if not isinstance(shapes, list) or not shapes:
        problems.append("geometry needs a non-empty shapes list")
        return
    for n, shape in enumerate(shapes, start=1):
        if not isinstance(shape, dict):
            problems.append(f"shape {n} must be an object")
            continue
        kind = shape.get("shape")
        if kind not in SHAPES:
            problems.append(f"shape {n} must be one of {', '.join(SHAPES)}")
            continue
        _label(shape.get("label"), f"shape {n}", problems)
        if kind == "triangle":
            _strict(set(shape), {"shape", "a", "b", "c", "label"}, f"shape {n}", problems)
            for corner in ("a", "b", "c"):
                _point(shape.get(corner), f"shape {n} {corner}", problems)
        elif kind == "line":
            _strict(set(shape), {"shape", "a", "b", "label"}, f"shape {n}", problems)
            _point(shape.get("a"), f"shape {n} a", problems)
            _point(shape.get("b"), f"shape {n} b", problems)
        elif kind == "rectangle":
            _strict(set(shape), {"shape", "x", "y", "w", "h", "label"}, f"shape {n}", problems)
            for key in ("x", "y"):
                if not _is_num(shape.get(key)):
                    problems.append(f"shape {n} {key} must be a number")
            for key in ("w", "h"):
                if not _is_num(shape.get(key)) or shape.get(key) is not None and shape[key] <= 0:
                    problems.append(f"shape {n} {key} must be a positive number")
        else:  # circle
            _strict(set(shape), {"shape", "at", "r", "label"}, f"shape {n}", problems)
            _point(shape.get("at"), f"shape {n} at", problems)
            if not _is_num(shape.get("r")) or shape.get("r") is not None and shape["r"] <= 0:
                problems.append(f"shape {n} r must be a positive number")


def _circuit(spec: dict, problems: list) -> None:
    _strict(set(spec) & ELEMENT_KEYS,
           {"wires", "components"}, "circuit spec", problems)
    wires = spec.get("wires", [])
    components = spec.get("components", [])
    if not isinstance(wires, list) or not isinstance(components, list):
        problems.append("wires and components must be lists")
        return
    if not wires and not components:
        problems.append("circuit needs at least one wire or component")
    for n, wire in enumerate(wires, start=1):
        if not isinstance(wire, dict):
            problems.append(f"wire {n} must be an object")
            continue
        _strict(set(wire), {"a", "b"}, f"wire {n}", problems)
        _point(wire.get("a"), f"wire {n} a", problems)
        _point(wire.get("b"), f"wire {n} b", problems)
    for n, component in enumerate(components, start=1):
        if not isinstance(component, dict):
            problems.append(f"component {n} must be an object")
            continue
        _strict(set(component), {"type", "at", "label"}, f"component {n}", problems)
        if component.get("type") not in COMPONENTS:
            problems.append(
                f"component {n} type must be one of {', '.join(COMPONENTS)}"
            )
        _point(component.get("at"), f"component {n} at", problems)
        _label(component.get("label"), f"component {n}", problems)


def _apparatus(spec: dict, problems: list) -> None:
    _strict(set(spec) & ELEMENT_KEYS, {"components"}, "apparatus spec", problems)
    components = spec.get("components")
    if not isinstance(components, list) or not components:
        problems.append("apparatus needs a non-empty components list")
        return
    for n, component in enumerate(components, start=1):
        if not isinstance(component, dict):
            problems.append(f"component {n} must be an object")
            continue
        _strict(set(component), {"type", "at", "label"}, f"component {n}", problems)
        if component.get("type") not in APPARATUS:
            problems.append(
                f"component {n} type must be one of {', '.join(APPARATUS)}"
            )
        _point(component.get("at"), f"component {n} at", problems)
        _label(component.get("label"), f"component {n}", problems)


def _ray(spec: dict, problems: list) -> None:
    _strict(set(spec) & ELEMENT_KEYS, {"rays", "optics"}, "ray spec", problems)
    rays = spec.get("rays", [])
    optics = spec.get("optics", [])
    if not isinstance(rays, list) or not isinstance(optics, list):
        problems.append("rays and optics must be lists")
        return
    if not rays:
        problems.append("ray diagrams need at least one ray")
    for n, ray in enumerate(rays, start=1):
        if not isinstance(ray, dict):
            problems.append(f"ray {n} must be an object")
            continue
        _strict(set(ray), {"a", "b", "label"}, f"ray {n}", problems)
        _point(ray.get("a"), f"ray {n} a", problems)
        _point(ray.get("b"), f"ray {n} b", problems)
        _label(ray.get("label"), f"ray {n}", problems)
    for n, optic in enumerate(optics, start=1):
        if not isinstance(optic, dict):
            problems.append(f"optic {n} must be an object")
            continue
        _strict(set(optic), {"type", "at", "label"}, f"optic {n}", problems)
        if optic.get("type") not in OPTICS:
            problems.append(f"optic {n} type must be one of {', '.join(OPTICS)}")
        _point(optic.get("at"), f"optic {n} at", problems)
        _label(optic.get("label"), f"optic {n}", problems)
