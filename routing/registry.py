"""The model registry: known models, their roles, and their prices.

Prices are operator data, not code: var/routing/prices.json maps model names
to {"in_per_1k": dollars, "out_per_1k": dollars}. Unknown models and missing
prices cost nothing on paper — the dashboard says "unpriced" rather than
inventing a number.
"""

from __future__ import annotations

import json
from pathlib import Path

REGISTRY = {
    "muse-spark-1.3": {
        "roles": ["agent", "judge", "transcribe"],
        "notes": "Default agent + transcription model.",
    },
    "muse-spark-1.3-judge": {
        "roles": ["judge"],
        "notes": "Default independent judge (set JUDGE_MODEL to the review deployment).",
    },
    "sam-3.1": {
        "roles": ["segment"],
        "notes": "Segmentation for signature checks.",
    },
}


class RegistryError(ValueError):
    pass


def get(name: str) -> dict:
    """A registry entry, or raise RegistryError."""
    if name not in REGISTRY:
        raise RegistryError(
            f"unknown model {name!r}; known: {', '.join(sorted(REGISTRY))}"
        )
    return REGISTRY[name]


def prices_path(var_dir: Path) -> Path:
    return Path(var_dir) / "routing" / "prices.json"


def prices(var_dir: Path) -> dict:
    """Configured prices ({model: {in_per_1k, out_per_1k}}); {} when unset."""
    path = prices_path(var_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def cost_usd(var_dir: Path, model: str, input_tokens: int, output_tokens: int) -> float | None:
    """One call's cost, or None when the model is unpriced."""
    entry = prices(var_dir).get(model)
    if not entry:
        return None
    try:
        return round(
            input_tokens / 1000 * float(entry["in_per_1k"])
            + output_tokens / 1000 * float(entry["out_per_1k"]),
            6,
        )
    except (KeyError, TypeError, ValueError):
        return None
