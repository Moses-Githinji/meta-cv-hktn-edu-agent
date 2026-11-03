"""The static role table: which model serves each role.

Roles: "agent" (MODEL_API_MODEL, default muse-spark-1.3) and "judge"
(JUDGE_MODEL, default muse-spark-1.3-judge). resolve_pair() returns the
(generator, judge) pair and enforces the hard rule: the judge never equals
the generator. Performance-based choice (performance.py) may propose a
different generator later; the rule still applies to whatever it proposes.
"""

from __future__ import annotations

from edu_kit.settings import judge_model, model


class RoutingError(ValueError):
    """No valid routing (judge equals generator)."""


def resolve(role: str) -> str:
    """The model for a role ("agent" or "judge")."""
    if role == "agent":
        return model()
    if role == "judge":
        return judge_model()
    raise RoutingError(f"unknown role {role!r}; roles: agent, judge")


def resolve_pair(generator: str | None = None, judge: str | None = None) -> tuple:
    """The (generator, judge) pair; refuses when they are equal."""
    generator = generator or model()
    judge = judge or judge_model()
    if generator == judge:
        raise RoutingError(
            f"the judge model must differ from the agent model ({generator}); set JUDGE_MODEL"
        )
    return generator, judge
