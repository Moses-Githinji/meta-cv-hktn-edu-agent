"""Load and validate the one-term curriculum pack (stdlib only).

Usage:
    python3 curriculum/loader.py --check
    python3 -c "from curriculum.loader import load_pack; pack = load_pack()"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACK_FILENAME = "grade7-mathematics-term1.json"
PACK_PATH = Path(__file__).resolve().parent / PACK_FILENAME

# Packs the system knows how to work: (learning_area, grade, curriculum).
# Adding a subject or level means adding its combo here, its pack file, and
# its eval tasks (see EXPANSION.md) — never loosening the loader silently.
SUPPORTED = {
    ("Mathematics", 7, "CBC"),
    ("Christian Religious Education", 7, "CBC"),
    ("English", 7, "CBC"),
    ("Kiswahili", 7, "CBC"),
    ("Agriculture", 7, "CBC"),
    ("French", 7, "CBC"),
}


class PackError(ValueError):
    pass


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise PackError(message)


def load_pack(path: Path = PACK_PATH) -> dict:
    """Read the pack JSON and validate its structure (mirrors schema.json)."""
    try:
        pack = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise PackError(f"cannot read pack {path}: {error}") from error

    _need(isinstance(pack, dict), "pack root must be an object")
    for key in ("pack", "source", "term", "strands"):
        _need(key in pack, f"pack is missing {key!r}")

    meta = pack["pack"]
    combo = (meta.get("learning_area"), meta.get("grade"), meta.get("curriculum"))
    _need(
        combo in SUPPORTED,
        f"unsupported pack {meta.get('learning_area')} grade {meta.get('grade')} "
        f"{meta.get('curriculum')}; supported: "
        + ", ".join(f"{a} grade {g} {c}" for a, g, c in sorted(SUPPORTED)),
    )
    _need(pack["source"].get("publisher") == "Kenya Institute of Curriculum Development",
          "pack source must be KICD")

    _need(isinstance(pack["strands"], list) and pack["strands"], "need >= 1 strand")
    seen: set[str] = set()
    for strand in pack["strands"]:
        for sub in strand.get("sub_strands", []):
            weeks = sub.get("week_range", [])
            _need(len(weeks) == 2 and weeks[0] <= weeks[1],
                  f"{sub.get('id')}: bad week_range {weeks}")
            _need(sub.get("outcomes"), f"{sub.get('id')}: need >= 1 outcome")
            for outcome in sub["outcomes"]:
                oid = outcome.get("id", "")
                _need(oid and oid not in seen, f"duplicate or empty outcome id {oid!r}")
                seen.add(oid)
                _need(outcome.get("outcome_text"), f"{oid}: empty outcome_text")
                _need(outcome.get("source_ref"), f"{oid}: empty source_ref")
                _need(outcome.get("status") in ("transcribed", "pending_transcription"),
                      f"{oid}: bad status {outcome.get('status')!r}")
                for field in ("suggested_learning_experiences", "key_inquiry_questions",
                              "assessment", "learning_resources"):
                    value = outcome.get(field)
                    if value is not None:
                        _need(isinstance(value, list) and value and all(
                            isinstance(s, str) and s.strip() for s in value),
                            f"{oid}: bad {field} (want a non-empty string list)")
                if outcome["status"] == "transcribed":
                    _need(outcome["outcome_text"] != "TODO_TRANSCRIBE",
                          f"{oid}: marked transcribed but text is still a stub")
    return pack


def find_outcome(pack: dict, outcome_id: str) -> dict | None:
    """One outcome by id, with its strand/sub-strand context, or None."""
    for strand in pack.get("strands", []):
        for sub in strand.get("sub_strands", []):
            for outcome in sub.get("outcomes", []):
                if outcome.get("id") == outcome_id:
                    return {
                        "strand_id": strand.get("id"),
                        "strand": strand.get("name"),
                        "sub_strand_id": sub.get("id"),
                        "sub_strand": sub.get("name"),
                        "week_range": sub.get("week_range"),
                        **outcome,
                    }
    return None


def coverage(pack: dict) -> dict:
    """Transcription coverage: transcribed / total outcomes."""
    total = done = 0
    pending: list[str] = []
    for strand in pack["strands"]:
        for sub in strand["sub_strands"]:
            for outcome in sub["outcomes"]:
                total += 1
                if outcome["status"] == "transcribed":
                    done += 1
                else:
                    pending.append(outcome["id"])
    return {"transcribed": done, "total": total, "pending": pending}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the curriculum packs.")
    parser.add_argument("--check", action="store_true", help="validate and report coverage")
    parser.add_argument("files", nargs="*", help="pack files to check (default: all)")
    args = parser.parse_args(argv)
    paths = [Path(f) for f in args.files] or sorted(
        p for p in PACK_PATH.parent.glob("*.json") if p.name != "schema.json"
    )
    failed = False
    for path in paths:
        try:
            pack = load_pack(path)
        except PackError as error:
            print(f"PACK INVALID {path.name}: {error}", file=sys.stderr)
            failed = True
            continue
        if args.check:
            cov = coverage(pack)
            print(f"pack {pack['pack']['id']} v{pack['pack']['version']}: valid")
            print(f"transcribed {cov['transcribed']}/{cov['total']}"
                  + (f"; pending: {', '.join(cov['pending'])}" if cov["pending"] else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
