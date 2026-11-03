"""Run settings read from the environment (./helper loads .env)."""

from __future__ import annotations

import os
from pathlib import Path

from curriculum.loader import PACK_FILENAME

_TRUE = {"on", "1", "true", "yes"}
DEFAULT_PACK = PACK_FILENAME.removesuffix(".json")


def model() -> str:
    """The model the agent talks to (MODEL_API_MODEL, default muse-spark-1.3)."""
    return os.environ.get("MODEL_API_MODEL") or "muse-spark-1.3"


def sam_model() -> str:
    """The segmentation model check_signatures uses (SAM_MODEL, default sam-3.1)."""
    return os.environ.get("SAM_MODEL") or "sam-3.1"


def judge_model() -> str:
    """The independent judge model (JUDGE_MODEL).

    Independent verification judges the filed document with this model, which
    must differ from the agent model so one model's blind spot cannot clear
    its own work. Set JUDGE_MODEL to the review deployment; the default is a
    distinct value so the two never silently share a model.
    """
    return os.environ.get("JUDGE_MODEL") or "muse-spark-1.3-judge"


def verification_enabled() -> bool:
    """VERIFICATION=on: new runs get the verification layer (agent/verification/): the
    checks run at fixed points, three more tools, escalation, and attorney sign-off."""
    return os.environ.get("VERIFICATION", "off").strip().lower() in _TRUE


def curriculum_pack_id() -> str:
    """The curriculum pack id (curriculum/<id>.json) the tools read.

    CURRICULUM_PACK wins when set; otherwise the teaching pack's own folder
    name, so switching tasks switches curricula with it; otherwise the
    default pack. Runs also store this id on the record, so review and
    verification keep reading the run's own pack after you switch away.
    """
    explicit = os.environ.get("CURRICULUM_PACK", "").strip()
    if explicit:
        return explicit
    teaching = os.environ.get("TEACHING_PACK_DIR", "").strip()
    if teaching:
        return Path(teaching).name
    return DEFAULT_PACK


def teaching_pack_dir(root: Path) -> Path:
    """The case folder (TEACHING_PACK_DIR, absolute or relative to the agent folder): objective.md and documents/."""
    value = os.environ.get("TEACHING_PACK_DIR", "").strip()
    if not value:
        raise RuntimeError("TEACHING_PACK_DIR is not set: point it at a case folder in .env")
    path = Path(value).expanduser()
    return path if path.is_absolute() else (Path(root) / path).resolve()
