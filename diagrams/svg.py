"""SVG renderer: drawings in, standalone SVG documents out.

Every primitive carries data-el (its spec element index, or "frame") and
data-label, which the independent read-back (readback.py) parses. Output is
deterministic: the same spec always yields the same bytes.
"""

from __future__ import annotations

from xml.sax.saxutils import escape


def emit(drawing: dict) -> str:
    """A drawing (see layout.py) as an SVG document string."""
    width, height = drawing["width"], drawing["height"]
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" data-kind="{drawing["kind"]}" '
        f'data-title="{escape(drawing["title"])}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="white" data-el="frame"/>',
    ]
    for primitive in drawing["primitives"]:
        lines.append(_emit(primitive))
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _emit(primitive: dict) -> str:
    el = primitive.get("el", "frame")
    label = escape(str(primitive.get("label", "")))
    attrs = f'data-el="{el}" data-label="{label}"'
    shape = primitive["shape"]
    if shape == "line":
        stroke = "#cccccc" if primitive.get("tone") == "grid" else "black"
        return (
            f'<line x1="{primitive["x1"]}" y1="{primitive["y1"]}" '
            f'x2="{primitive["x2"]}" y2="{primitive["y2"]}" '
            f'stroke="{stroke}" stroke-width="2" {attrs}/>'
        )
    if shape == "rect":
        return (
            f'<rect x="{primitive["x"]}" y="{primitive["y"]}" '
            f'width="{primitive["w"]}" height="{primitive["h"]}" '
            f'fill="none" stroke="black" stroke-width="2" {attrs}/>'
        )
    if shape == "circle":
        fill = "black" if primitive.get("fill") else "none"
        stroke = "none" if primitive.get("fill") else "black"
        return (
            f'<circle cx="{primitive["cx"]}" cy="{primitive["cy"]}" '
            f'r="{primitive["r"]}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="2" {attrs}/>'
        )
    size = 16 if primitive.get("size", 1) > 1 else 11
    anchor = "middle" if el == "frame" and primitive.get("size", 1) > 1 else "start"
    return (
        f'<text x="{primitive["x"]}" y="{primitive["y"]}" font-size="{size}" '
        f'text-anchor="{anchor}" font-family="sans-serif" {attrs}>'
        f"{escape(primitive['text'])}</text>"
    )
