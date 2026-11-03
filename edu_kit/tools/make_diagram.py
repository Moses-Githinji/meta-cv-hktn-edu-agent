"""make_diagram: render a diagram spec to SVG + PNG and file it as a figure.

The spec is validated first (see check_diagram); failures come back as an
error to fix, not a figure. Renders land under the run's figures/ folder and
are recorded on the case as fig-N, ready to cite from lesson plans, exams,
and exports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from diagrams import layout as layout_module
from diagrams import png as png_module
from diagrams import svg as svg_module
from diagrams.spec import validate_spec

if TYPE_CHECKING:
    from . import Context

DEFINITION = {
    "type": "function",
    "name": "make_diagram",
    "description": "Render a diagram spec (kind graph, geometry, circuit, apparatus, or ray) "
    "to a filed figure (fig-N) with SVG and PNG. Validate cheaply first with check_diagram.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "spec": {
                "type": "object",
                "description": "the diagram spec to render",
            },
        },
        "required": ["spec"],
    },
}


def run(ctx: Context, args: dict) -> dict:
    spec = args.get("spec")
    if not isinstance(spec, dict):
        return {"error": "spec must be an object"}
    problems = validate_spec(spec)
    if problems:
        return {"error": "spec invalid", "problems": problems}
    drawing = layout_module.layout(spec)
    svg_text = svg_module.emit(drawing)
    png_bytes = png_module.render(drawing)
    folder = ctx.root / "workspace/runs" / ctx.run_id / "figures"
    folder.mkdir(parents=True, exist_ok=True)
    number = len(ctx.case.data.get("figures", [])) + 1
    svg_path = folder / f"fig-{number}.svg"
    png_path = folder / f"fig-{number}.png"
    svg_path.write_text(svg_text)
    png_path.write_bytes(png_bytes)
    figure = ctx.case.add_figure(
        {
            "kind": spec["kind"],
            "title": spec["title"],
            "caption": str(spec.get("caption") or spec["title"]),
            "svg": str(svg_path.relative_to(ctx.root)),
            "png": str(png_path.relative_to(ctx.root)),
        }
    )
    return {"figure": figure}
