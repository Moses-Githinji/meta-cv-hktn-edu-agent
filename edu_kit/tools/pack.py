"""Shared helper: load the curriculum pack the agent works from (offline).

The pack file lives under the run root at curriculum/<pack>.json. The id is
the run's own stored pack first, then settings.curriculum_pack_id()
(CURRICULUM_PACK, else the teaching pack's folder, else the default); the
loader validates it. Raises curriculum.loader.PackError when unreadable,
which each tool reports as an error the model can read.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from curriculum.loader import PACK_FILENAME, PackError, load_pack
from edu_kit.settings import curriculum_pack_id

if TYPE_CHECKING:
    from . import Context

DEFAULT_PACK = PACK_FILENAME.removesuffix(".json")


def pack_id() -> str:
    """The curriculum pack id from the environment (no run involved)."""
    return curriculum_pack_id()


def resolve(root: Path, run_pack: str | None = None) -> Path | None:
    """The pack file to read: the run's own pack first, then env, then default.

    Each candidate must exist as a file; the default keeps fixture roots
    (which carry only the default pack file) working whatever the
    environment says. None when this root works no teaching pack at all.
    """
    candidates = ([run_pack] if run_pack else []) + [pack_id(), DEFAULT_PACK]
    for candidate in dict.fromkeys(candidates):
        found = Path(root) / "curriculum" / f"{candidate}.json"
        if found.is_file():
            return found
    return None


def path(root: Path) -> Path:
    """The pack file for the environment, defaulting to the default pack file.

    Falls back to the named (missing) path when nothing exists, so the
    loader's error names the file that was asked for.
    """
    return resolve(root) or Path(root) / "curriculum" / f"{pack_id()}.json"


def exists(root: Path) -> bool:
    """Whether this root works a teaching pack (routes teaching vs legal checks)."""
    return resolve(root) is not None


def load(ctx: Context) -> dict:
    case_pack = ctx.case.data.get("pack") if ctx.case is not None else None
    found = resolve(ctx.root, case_pack)
    if found is None:
        raise PackError(f"no teaching pack found under {Path(ctx.root) / 'curriculum'}")
    return load_pack(found)
