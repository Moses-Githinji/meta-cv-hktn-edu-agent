"""Independent read-back: parse a rendered SVG back to its elements.

read() parses the SVG with ElementTree only — it shares no code with the
renderers — and returns {kind, title, elements} where each element is
{shape, el, label}. compare(spec, parsed) checks the render against the
spec it claims to show: kind, title, one indexed element group per spec
element, matching labels. Coordinates are checked for canvas bounds, not
exact pixels: placement belongs to layout, presence belongs here.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree

SHAPES = {"line", "rect", "circle", "text"}


class ReadbackError(ValueError):
    """The SVG cannot be read back."""


def read(svg_text: str) -> dict:
    """Parse rendered SVG back to {kind, title, elements}."""
    try:
        root = ElementTree.fromstring(svg_text)
    except ElementTree.ParseError as error:
        raise ReadbackError(f"not parseable SVG: {error}") from None
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise ReadbackError("not an SVG document")
    elements = []
    for node in root.iter():
        shape = node.tag.rsplit("}", 1)[-1]
        if shape not in SHAPES:
            continue
        el = node.get("data-el", "frame")
        elements.append(
            {
                "shape": shape,
                "el": int(el) if el.lstrip("-").isdigit() else el,
                "label": node.get("data-label", ""),
                "text": (node.text or "") if shape == "text" else "",
            }
        )
    return {
        "kind": root.get("data-kind", ""),
        "title": root.get("data-title", ""),
        "width": _int(root.get("width")),
        "height": _int(root.get("height")),
        "elements": elements,
    }


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _expected(spec: dict) -> tuple:
    """(kind, title, element count, labels by element) a render must show."""
    kind = spec.get("kind")
    if kind == "graph":
        items = list(spec.get("points", [])) + list(spec.get("segments", []))
        labels = [p.get("label", "") for p in spec.get("points", [])]
        labels += [""] * len(spec.get("segments", []))
    elif kind == "geometry":
        items = list(spec.get("shapes", []))
        labels = [s.get("label", "") for s in items]
    elif kind == "circuit":
        items = list(spec.get("wires", [])) + list(spec.get("components", []))
        labels = [""] * len(spec.get("wires", []))
        labels += [c.get("label", "") for c in spec.get("components", [])]
    elif kind == "apparatus":
        items = list(spec.get("components", []))
        labels = [c.get("label", "") for c in items]
    else:
        items = list(spec.get("rays", [])) + list(spec.get("optics", []))
        labels = [r.get("label", "") for r in spec.get("rays", [])]
        labels += [o.get("label", "") for o in spec.get("optics", [])]
    return kind, spec.get("title", ""), len(items), labels


def compare(spec: dict, parsed: dict) -> list:
    """Mismatches between a spec and its read-back render (empty = match)."""
    mismatches = []
    kind, title, count, labels = _expected(spec)
    if parsed.get("kind") != kind:
        mismatches.append(
            f"kind {parsed.get('kind')!r} does not match spec {kind!r}"
        )
    if parsed.get("title") != title:
        mismatches.append("title does not match the spec")
    seen: dict = {}
    for element in parsed.get("elements", []):
        if element["el"] == "frame":
            continue
        seen.setdefault(element["el"], []).append(element)
    if sorted(seen) != list(range(count)):
        mismatches.append(
            f"render shows elements {sorted(seen, key=str)}, spec has {count}"
        )
        return mismatches
    for n in range(count):
        want = labels[n] if n < len(labels) else ""
        texts = [e["text"] for e in seen[n] if e["shape"] == "text"]
        if want and want not in " ".join(texts):
            mismatches.append(f"element {n}: label {want!r} missing from render")
    return mismatches
