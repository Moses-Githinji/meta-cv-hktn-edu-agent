"""Diagram layout: validated specs in, pixel-space drawings out.

layout(spec) maps each kind onto a 600x400 canvas and returns a drawing:
{"width", "height", "kind", "title", "primitives"} where each primitive is
{"shape": "line"|"rect"|"circle"|"text", ...pixel coords..., "el": index |
"frame", "label": ...}. The SVG and PNG renderers share the drawing, so both
outputs agree pixel for pixel. Deterministic: no timestamps, no randomness.
"""

from __future__ import annotations

WIDTH = 600
HEIGHT = 400
_MARGIN = {"left": 60, "right": 20, "top": 34, "bottom": 40}


def layout(spec: dict) -> dict:
    """A validated spec as pixel-space primitives."""
    kind = spec["kind"]
    if kind == "graph":
        primitives = _graph(spec)
    elif kind == "geometry":
        primitives = _geometry(spec)
    elif kind == "circuit":
        primitives = _circuit(spec)
    elif kind == "apparatus":
        primitives = _apparatus(spec)
    else:
        primitives = _ray(spec)
    primitives.append(
        {
            "shape": "text",
            "x": WIDTH // 2,
            "y": 16,
            "text": spec["title"],
            "size": 2,
            "el": "frame",
            "label": "",
        }
    )
    return {
        "width": WIDTH,
        "height": HEIGHT,
        "kind": kind,
        "title": spec["title"],
        "primitives": primitives,
    }


def _graph(spec: dict) -> list:
    x0, x1 = spec["x"]["min"], spec["x"]["max"]
    y0, y1 = spec["y"]["min"], spec["y"]["max"]
    left, top = _MARGIN["left"], _MARGIN["top"]
    plot_w = WIDTH - left - _MARGIN["right"]
    plot_h = HEIGHT - top - _MARGIN["bottom"]

    def px(x: float) -> int:
        return round(left + (x - x0) / (x1 - x0) * plot_w)

    def py(y: float) -> int:
        return round(top + plot_h - (y - y0) / (y1 - y0) * plot_h)

    out: list = []
    if spec.get("grid", True):
        for i in range(6):
            gx = round(left + i / 5 * plot_w)
            gy = round(top + i / 5 * plot_h)
            out.append(
                {"shape": "line", "x1": gx, "y1": top, "x2": gx, "y2": top + plot_h,
                 "el": "frame", "label": "", "tone": "grid"}
            )
            out.append(
                {"shape": "line", "x1": left, "y1": gy, "x2": left + plot_w, "y2": gy,
                 "el": "frame", "label": "", "tone": "grid"}
            )
    out.append(
        {"shape": "line", "x1": left, "y1": py(0) if y0 <= 0 <= y1 else top + plot_h,
         "x2": left + plot_w, "y2": py(0) if y0 <= 0 <= y1 else top + plot_h,
         "el": "frame", "label": ""}
    )
    out.append(
        {"shape": "line", "x1": px(0) if x0 <= 0 <= x1 else left, "y1": top,
         "x2": px(0) if x0 <= 0 <= x1 else left, "y2": top + plot_h,
         "el": "frame", "label": ""}
    )
    if spec["x"].get("label"):
        out.append({"shape": "text", "x": left + plot_w, "y": top + plot_h + 18,
                    "text": spec["x"]["label"], "size": 1, "el": "frame", "label": ""})
    if spec["y"].get("label"):
        out.append({"shape": "text", "x": 6, "y": top + 8,
                    "text": spec["y"]["label"], "size": 1, "el": "frame", "label": ""})
    for n, point in enumerate(spec.get("points", [])):
        cx, cy = px(point["x"]), py(point["y"])
        out.append({"shape": "circle", "cx": cx, "cy": cy, "r": 4, "fill": True,
                    "el": n, "label": point.get("label", "")})
        if point.get("label"):
            out.append({"shape": "text", "x": cx + 7, "y": cy - 4,
                        "text": point["label"], "size": 1, "el": n, "label": ""})
    base = len(spec.get("points", []))
    for n, segment in enumerate(spec.get("segments", []), start=base):
        out.append({"shape": "line", "x1": px(segment["a"][0]), "y1": py(segment["a"][1]),
                    "x2": px(segment["b"][0]), "y2": py(segment["b"][1]),
                    "el": n, "label": ""})
    return out


def _fit(points: list) -> tuple:
    """Scale + offset fitting abstract points into the plot area."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    span_x = max(max(xs) - min(xs), 1e-9)
    span_y = max(max(ys) - min(ys), 1e-9)
    plot_w = WIDTH - _MARGIN["left"] - _MARGIN["right"]
    plot_h = HEIGHT - _MARGIN["top"] - _MARGIN["bottom"]
    scale = min(plot_w / span_x, plot_h / span_y, 120.0)
    ox = _MARGIN["left"] + (plot_w - span_x * scale) / 2 - min(xs) * scale
    oy = _MARGIN["top"] + (plot_h - span_y * scale) / 2 - min(ys) * scale
    return scale, ox, oy


def _geometry(spec: dict) -> list:
    corners: list = []
    for shape in spec["shapes"]:
        if shape["shape"] == "triangle":
            corners.extend([shape["a"], shape["b"], shape["c"]])
        elif shape["shape"] == "line":
            corners.extend([shape["a"], shape["b"]])
        elif shape["shape"] == "rectangle":
            corners.extend(
                [
                    (shape["x"], shape["y"]),
                    (shape["x"] + shape["w"], shape["y"] + shape["h"]),
                ]
            )
        else:
            corners.extend(
                [
                    (shape["at"][0] - shape["r"], shape["at"][1] - shape["r"]),
                    (shape["at"][0] + shape["r"], shape["at"][1] + shape["r"]),
                ]
            )
    scale, ox, oy = _fit(corners)

    def px(x: float) -> int:
        return round(ox + x * scale)

    def py(y: float) -> int:
        return round(oy + y * scale)

    out: list = []
    for n, shape in enumerate(spec["shapes"]):
        label = shape.get("label", "")
        if shape["shape"] == "triangle":
            a, b, c = [(px(p[0]), py(p[1])) for p in (shape["a"], shape["b"], shape["c"])]
            for p, q in ((a, b), (b, c), (c, a)):
                out.append({"shape": "line", "x1": p[0], "y1": p[1], "x2": q[0],
                            "y2": q[1], "el": n, "label": ""})
            anchor = ((a[0] + b[0] + c[0]) // 3, (a[1] + b[1] + c[1]) // 3)
        elif shape["shape"] == "line":
            a, b = (px(shape["a"][0]), py(shape["a"][1])), (px(shape["b"][0]), py(shape["b"][1]))
            out.append({"shape": "line", "x1": a[0], "y1": a[1], "x2": b[0],
                        "y2": b[1], "el": n, "label": ""})
            anchor = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
        elif shape["shape"] == "rectangle":
            x, y = px(shape["x"]), py(shape["y"])
            out.append({"shape": "rect", "x": x, "y": y,
                        "w": round(shape["w"] * scale), "h": round(shape["h"] * scale),
                        "el": n, "label": ""})
            anchor = (x, y - 6)
        else:
            cx, cy = px(shape["at"][0]), py(shape["at"][1])
            out.append({"shape": "circle", "cx": cx, "cy": cy,
                        "r": max(round(shape["r"] * scale), 2), "el": n, "label": ""})
            anchor = (cx, cy)
        if label:
            out.append({"shape": "text", "x": anchor[0] + 4, "y": anchor[1] - 4,
                        "text": label, "size": 1, "el": n, "label": ""})
    return out


def _circuit(spec: dict) -> list:
    points: list = []
    for wire in spec.get("wires", []):
        points.extend([wire["a"], wire["b"]])
    for component in spec.get("components", []):
        points.extend(
            [
                (component["at"][0] - 0.6, component["at"][1] - 0.6),
                (component["at"][0] + 0.6, component["at"][1] + 0.6),
            ]
        )
    scale, ox, oy = _fit(points or [[0, 0], [4, 3]])

    def px(x: float) -> int:
        return round(ox + x * scale)

    def py(y: float) -> int:
        return round(oy + y * scale)

    out: list = []
    for n, wire in enumerate(spec.get("wires", [])):
        out.append({"shape": "line", "x1": px(wire["a"][0]), "y1": py(wire["a"][1]),
                    "x2": px(wire["b"][0]), "y2": py(wire["b"][1]),
                    "el": n, "label": ""})
    base = len(spec.get("wires", []))
    for n, component in enumerate(spec.get("components", []), start=base):
        cx, cy = px(component["at"][0]), py(component["at"][1])
        glyph, _ = _glyph(component["type"], cx, cy, scale)
        for primitive in glyph:
            out.append({**primitive, "el": n, "label": ""})
        if component.get("label"):
            out.append({"shape": "text", "x": cx + 8, "y": cy - 8,
                        "text": component["label"], "size": 1, "el": n, "label": ""})
    return out


def _glyph(kind: str, cx: int, cy: int, scale: float) -> tuple:
    """A circuit component glyph as primitives (plus its half-size)."""
    half = max(round(0.3 * scale), 6)
    if kind == "battery":
        return [
            {"shape": "line", "x1": cx - half, "y1": cy - half // 2,
             "x2": cx + half, "y2": cy - half // 2},
            {"shape": "line", "x1": cx - half // 2, "y1": cy + half // 2,
             "x2": cx + half // 2, "y2": cy + half // 2},
        ], half
    if kind == "bulb":
        return [
            {"shape": "circle", "cx": cx, "cy": cy, "r": half},
            {"shape": "line", "x1": cx - half, "y1": cy - half,
             "x2": cx + half, "y2": cy + half},
            {"shape": "line", "x1": cx - half, "y1": cy + half,
             "x2": cx + half, "y2": cy - half},
        ], half
    if kind == "resistor":
        points = [
            (cx - half, cy),
            (cx - half // 2, cy - half // 2),
            (cx, cy + half // 2),
            (cx + half // 2, cy - half // 2),
            (cx + half, cy),
        ]
        return [
            {"shape": "line", "x1": a[0], "y1": a[1], "x2": b[0], "y2": b[1]}
            for a, b in zip(points, points[1:])
        ], half
    # switch: two terminals and an open blade
    return [
        {"shape": "circle", "cx": cx - half, "cy": cy, "r": 2, "fill": True},
        {"shape": "circle", "cx": cx + half, "cy": cy, "r": 2, "fill": True},
        {"shape": "line", "x1": cx - half, "y1": cy,
         "x2": cx + half - 2, "y2": cy - half},
    ], half


def _apparatus(spec: dict) -> list:
    points: list = []
    for component in spec["components"]:
        points.extend(
            [
                (component["at"][0] - 0.7, component["at"][1] - 0.7),
                (component["at"][0] + 0.7, component["at"][1] + 0.7),
            ]
        )
    scale, ox, oy = _fit(points)

    def px(x: float) -> int:
        return round(ox + x * scale)

    def py(y: float) -> int:
        return round(oy + y * scale)

    out: list = []
    for n, component in enumerate(spec["components"]):
        cx, cy = px(component["at"][0]), py(component["at"][1])
        for primitive in _apparatus_glyph(component["type"], cx, cy, scale):
            out.append({**primitive, "el": n, "label": ""})
        if component.get("label"):
            out.append({"shape": "text", "x": cx + 8, "y": cy - 8,
                        "text": component["label"], "size": 1, "el": n, "label": ""})
    return out


def _apparatus_glyph(kind: str, cx: int, cy: int, scale: float) -> list:
    """Lab glassware outlines from rects, lines, and circles."""
    half = max(round(0.3 * scale), 8)
    if kind == "beaker":
        return [
            {"shape": "line", "x1": cx - half, "y1": cy - half,
             "x2": cx - half, "y2": cy + half},
            {"shape": "line", "x1": cx - half, "y1": cy + half,
             "x2": cx + half, "y2": cy + half},
            {"shape": "line", "x1": cx + half, "y1": cy + half,
             "x2": cx + half, "y2": cy - half},
        ]
    if kind == "flask":
        return [
            {"shape": "line", "x1": cx - half // 3, "y1": cy - half,
             "x2": cx - half // 3, "y2": cy - half // 4},
            {"shape": "line", "x1": cx + half // 3, "y1": cy - half,
             "x2": cx + half // 3, "y2": cy - half // 4},
            {"shape": "line", "x1": cx - half // 3, "y1": cy - half // 4,
             "x2": cx - half, "y2": cy + half},
            {"shape": "line", "x1": cx + half // 3, "y1": cy - half // 4,
             "x2": cx + half, "y2": cy + half},
            {"shape": "line", "x1": cx - half, "y1": cy + half,
             "x2": cx + half, "y2": cy + half},
        ]
    if kind == "test_tube":
        return [
            {"shape": "line", "x1": cx - half // 2, "y1": cy - half,
             "x2": cx - half // 2, "y2": cy + half // 2},
            {"shape": "line", "x1": cx + half // 2, "y1": cy - half,
             "x2": cx + half // 2, "y2": cy + half // 2},
            {"shape": "line", "x1": cx - half // 2, "y1": cy + half // 2,
             "x2": cx + half // 2, "y2": cy + half // 2},
        ]
    # burner: base, barrel, and flame triangle
    return [
        {"shape": "line", "x1": cx - half, "y1": cy + half,
         "x2": cx + half, "y2": cy + half},
        {"shape": "rect", "x": cx - 3, "y": cy - half // 2, "w": 6, "h": half + half // 2},
        {"shape": "line", "x1": cx, "y1": cy - half // 2,
         "x2": cx - 4, "y2": cy - half},
        {"shape": "line", "x1": cx, "y1": cy - half // 2,
         "x2": cx + 4, "y2": cy - half},
    ]


def _ray(spec: dict) -> list:
    points: list = []
    for ray in spec.get("rays", []):
        points.extend([ray["a"], ray["b"]])
    for optic in spec.get("optics", []):
        points.extend(
            [
                (optic["at"][0] - 0.5, optic["at"][1] - 1.0),
                (optic["at"][0] + 0.5, optic["at"][1] + 1.0),
            ]
        )
    scale, ox, oy = _fit(points or [[0, 0], [4, 3]])

    def px(x: float) -> int:
        return round(ox + x * scale)

    def py(y: float) -> int:
        return round(oy + y * scale)

    out: list = []
    for n, ray in enumerate(spec.get("rays", [])):
        x1, y1, x2, y2 = px(ray["a"][0]), py(ray["a"][1]), px(ray["b"][0]), py(ray["b"][1])
        out.append({"shape": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                    "el": n, "label": ""})
        for tip in _arrowhead(x2, y2, x1, y1):
            out.append({**tip, "el": n, "label": ""})
        if ray.get("label"):
            out.append({"shape": "text", "x": x2 + 5, "y": y2 - 5,
                        "text": ray["label"], "size": 1, "el": n, "label": ""})
    base = len(spec.get("rays", []))
    for n, optic in enumerate(spec.get("optics", []), start=base):
        cx, cy = px(optic["at"][0]), py(optic["at"][1])
        arm = max(round(0.8 * scale), 10)
        if optic["type"] == "mirror":
            out.append({"shape": "line", "x1": cx, "y1": cy - arm,
                        "x2": cx, "y2": cy + arm, "el": n, "label": ""})
            for dy in (-arm, 0, arm):
                out.append({"shape": "line", "x1": cx, "y1": cy + dy,
                            "x2": cx - 6, "y2": cy + dy - 6, "el": n, "label": ""})
        else:  # lens: vertical ellipse hint from two arcs of short lines
            for sign in (-1, 1):
                out.append({"shape": "line", "x1": cx + sign * 6, "y1": cy - arm,
                            "x2": cx, "y2": cy, "el": n, "label": ""})
                out.append({"shape": "line", "x1": cx, "y1": cy,
                            "x2": cx + sign * 6, "y2": cy + arm, "el": n, "label": ""})
        if optic.get("label"):
            out.append({"shape": "text", "x": cx + 8, "y": cy - arm,
                        "text": optic["label"], "size": 1, "el": n, "label": ""})
    return out


def _arrowhead(tip_x: int, tip_y: int, from_x: int, from_y: int) -> list:
    """Two short barbs behind a ray tip, along its direction."""
    dx, dy = tip_x - from_x, tip_y - from_y
    length = max((dx * dx + dy * dy) ** 0.5, 1e-9)
    ux, uy = dx / length, dy / length
    size = 9
    left = (round(tip_x - ux * size - uy * size / 2), round(tip_y - uy * size + ux * size / 2))
    right = (round(tip_x - ux * size + uy * size / 2), round(tip_y - uy * size - ux * size / 2))
    return [
        {"shape": "line", "x1": tip_x, "y1": tip_y, "x2": left[0], "y2": left[1]},
        {"shape": "line", "x1": tip_x, "y1": tip_y, "x2": right[0], "y2": right[1]},
    ]
