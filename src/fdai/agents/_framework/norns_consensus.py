"""Deterministic three-perspective consensus for Norns proposals.

Urd, Verdandi, and Skuld are internal perspectives, not pantheon agents or
bus principals. They inspect the same inert RuleCandidate and return bounded
reason codes. Norns emits only their aggregate consensus result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

_ALLOWED_KINDS: frozenset[str] = frozenset(
    {"new", "new-scenario", "revision", "retirement", "threshold_adjustment"}
)
_AUTONOMY_RAISING_CHANGES: frozenset[str] = frozenset(
    {"auto_promote", "lower_confidence_threshold", "raise_autonomy"}
)


@dataclass(frozen=True, slots=True)
class PerspectiveVerdict:
    """One bounded perspective result without hidden reasoning text."""

    perspective: str
    accepted: bool
    reason_code: str


class CandidatePerspective(Protocol):
    """One deterministic view over an inert RuleCandidate."""

    name: str

    def inspect(self, candidate: dict[str, Any]) -> PerspectiveVerdict: ...


class UrdPerspective:
    """Past: require grounded evidence from an observed signal."""

    name = "Urd"

    def inspect(self, candidate: dict[str, Any]) -> PerspectiveVerdict:
        evidence = candidate.get("evidence")
        accepted = isinstance(evidence, dict) and bool(evidence)
        return PerspectiveVerdict(
            perspective=self.name,
            accepted=accepted,
            reason_code=(
                "historical_evidence_grounded" if accepted else "historical_evidence_missing"
            ),
        )


class VerdandiPerspective:
    """Present: require the current Norns candidate contract."""

    name = "Verdandi"

    def inspect(self, candidate: dict[str, Any]) -> PerspectiveVerdict:
        kind = str(candidate.get("proposal_kind", ""))
        accepted = (
            candidate.get("proposed_by") == "Norns"
            and bool(candidate.get("source_signal"))
            and kind in _ALLOWED_KINDS
        )
        return PerspectiveVerdict(
            perspective=self.name,
            accepted=accepted,
            reason_code="current_contract_valid" if accepted else "current_contract_invalid",
        )


class SkuldPerspective:
    """Future: reject candidates that directly raise autonomy."""

    name = "Skuld"

    def inspect(self, candidate: dict[str, Any]) -> PerspectiveVerdict:
        suggested_change = str(candidate.get("suggested_change", ""))
        enforcement_mode = str(candidate.get("enforcement_mode", ""))
        accepted = (
            suggested_change not in _AUTONOMY_RAISING_CHANGES
            and enforcement_mode != "enforce"
            and candidate.get("auto_promote") is not True
        )
        return PerspectiveVerdict(
            perspective=self.name,
            accepted=accepted,
            reason_code="future_safety_preserved" if accepted else "future_autonomy_increase",
        )


@dataclass(frozen=True, slots=True)
class NornsConsensusDecision:
    """Aggregate result from the three internal perspectives."""

    verdicts: tuple[PerspectiveVerdict, ...]

    @property
    def unanimous(self) -> bool:
        return len(self.verdicts) == 3 and all(verdict.accepted for verdict in self.verdicts)

    def summary(self) -> dict[str, object]:
        """Return the single bounded result allowed onto the bus."""
        return {
            "decision": "propose" if self.unanimous else "hold",
            "unanimous": self.unanimous,
            "perspective_count": len(self.verdicts),
            "reason_codes": list(self.reason_codes()),
        }

    def reason_codes(self) -> tuple[str, ...]:
        return tuple(verdict.reason_code for verdict in self.verdicts)

    def holding_perspectives(self) -> tuple[str, ...]:
        return tuple(verdict.perspective for verdict in self.verdicts if not verdict.accepted)


class NornsConsensus:
    """Require Urd, Verdandi, and Skuld to agree before publication."""

    def __init__(self) -> None:
        self._perspectives: tuple[CandidatePerspective, ...] = (
            UrdPerspective(),
            VerdandiPerspective(),
            SkuldPerspective(),
        )

    def evaluate(self, candidate: dict[str, Any]) -> NornsConsensusDecision:
        return NornsConsensusDecision(
            verdicts=tuple(perspective.inspect(candidate) for perspective in self._perspectives)
        )


__all__ = ["NornsConsensus", "NornsConsensusDecision", "PerspectiveVerdict"]
