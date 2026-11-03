#!/usr/bin/env python3
"""Export a run's documents to Word or PDF.

    ./helper export RUN_ID --what scheme|exam|marking-scheme|lesson-plan
        --format docx|pdf [--out FILE]

RUN_ID is the id ./helper run prints at the end. Missed it? It is the
folder name in workspace/runs/, or pick the run in the console's run list.

Figures number sequentially in order of appearance; the marking scheme
embeds each answer's figures; every page carries a footer. Default output:
workspace/runs/RUN_ID/<what>.<format>.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from export.build import WHAT, ExportError, build  # noqa: E402
from export.docx import build_docx  # noqa: E402
from export.pdf import build_pdf  # noqa: E402


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("run_id")
    parser.add_argument("--what", choices=WHAT, required=True)
    parser.add_argument("--format", choices=("docx", "pdf"), required=True)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    if not (ROOT / "workspace/case_records" / f"{args.run_id}.json").is_file():
        print(f"no case record for {args.run_id}", file=sys.stderr)
        return 1
    try:
        title, flow, footer = build(ROOT, args.run_id, args.what)
        landscape = args.what == "scheme"
        if args.format == "docx":
            data = build_docx(title, flow, footer, landscape=landscape)
        else:
            data = build_pdf(title, flow, footer, landscape=landscape)
    except ExportError as error:
        print(f"export failed: {error}", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else ROOT / "workspace/runs" / args.run_id / f"{args.what}.{args.format}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"{args.what} -> {out} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
