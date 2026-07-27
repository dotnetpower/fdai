"""The executor's blast-radius ceiling, in one place.

Three execution paths - the PR-publishing shadow executor, the direct-API
executor, and the tool-call executor - each carried a byte-identical copy of
this check. A ceiling enforced by three copies is a ceiling that will
eventually be enforced by two.

The rule is fail-closed. Every autonomous action is required to carry a
blast-radius limit, so an action that does not declare an affected count is not
a small action - it is an action whose reach cannot be evaluated, and this is
the last gate before a real mutation. The Action model defaults ``count`` to
``None`` and the internal action builder always fills it, so a ``None`` means
the Action arrived from somewhere that did not - which is exactly when a ceiling
matters.

``rate_per_minute`` stays optional: an action already bounded by count does not
need a rate to be bounded, and requiring one would refuse actions the builder
legitimately emits without it.
"""

from __future__ import annotations

from typing import Protocol

from fdai.shared.contracts.models import Action


class BlastRadiusCeiling(Protocol):
    """The executor-configured caps a blast radius is measured against."""

    @property
    def max_affected_resources(self) -> int: ...

    @property
    def max_rate_per_minute(self) -> int: ...


def blast_radius_refusal(action: Action, ceiling: BlastRadiusCeiling) -> str | None:
    """Return why ``action`` exceeds ``ceiling``, or ``None`` when it fits."""
    count = action.blast_radius.count
    if count is None:
        return (
            "blast-radius count is undeclared, so the affected-resource ceiling "
            f"({ceiling.max_affected_resources}) cannot be applied"
        )
    if count > ceiling.max_affected_resources:
        return f"blast-radius count {count} exceeds executor cap {ceiling.max_affected_resources}"
    rate_per_minute = action.blast_radius.rate_per_minute
    if rate_per_minute is not None and rate_per_minute > ceiling.max_rate_per_minute:
        return (
            f"blast-radius rate {rate_per_minute}/min exceeds executor cap "
            f"{ceiling.max_rate_per_minute}/min"
        )
    return None


__all__ = ["BlastRadiusCeiling", "blast_radius_refusal"]
