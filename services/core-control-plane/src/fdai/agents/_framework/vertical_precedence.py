"""Fixed execution-safety precedence for FDAI's initial verticals."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from fdai.core.risk_gate.precedence import (
    CandidateAction,
    PrecedenceOutcome,
    PrecedenceResolver,
    Vertical,
)

_DOMAIN_TO_VERTICAL: dict[str, Vertical] = {
    "resilience_safety_hold": Vertical.RESILIENCE_SAFETY_HOLD,
    "resilience": Vertical.RESILIENCE,
    "change_safety": Vertical.CHANGE_SAFETY,
    "cost": Vertical.COST,
    "cost_governance": Vertical.COST,
}


@runtime_checkable
class CrossVerticalPrecedence(Protocol):
    def winner(self, domains: Sequence[str]) -> str | None: ...


class InitialVerticalPrecedence:
    """Resolve only complete initial-vertical conflicts by fixed precedence."""

    def __init__(self, resolver: PrecedenceResolver | None = None) -> None:
        self._resolver = resolver or PrecedenceResolver()

    def winner(self, domains: Sequence[str]) -> str | None:
        normalized_pairs: list[tuple[str, str]] = []
        seen_keys: set[str] = set()
        for raw_domain in domains:
            original = str(raw_domain).strip()
            key = original.lower()
            if original and key not in seen_keys:
                seen_keys.add(key)
                normalized_pairs.append((original, key))
        if len(normalized_pairs) < 2:
            return None
        mapped = tuple(_DOMAIN_TO_VERTICAL.get(key) for _, key in normalized_pairs)
        if any(vertical is None for vertical in mapped) or len(set(mapped)) != len(mapped):
            return None
        decisions = self._resolver.resolve(
            CandidateAction(
                action_id=original,
                resource_id="shared-resource",
                vertical=vertical,
            )
            for (original, _), vertical in zip(normalized_pairs, mapped, strict=True)
            if vertical is not None
        )
        winner = next(
            (decision for decision in decisions if decision.outcome is PrecedenceOutcome.WIN),
            None,
        )
        return winner.action_id if winner is not None else None


__all__ = ["CrossVerticalPrecedence", "InitialVerticalPrecedence"]
