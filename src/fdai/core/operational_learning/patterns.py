"""Compile balanced observed-outcome cohorts into inert pattern candidates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PatternCase:
    case_id: str
    action_type: str
    outcome_id: str
    reusable: bool
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not all((self.case_id, self.action_type, self.outcome_id, self.evidence_refs)):
            raise ValueError("pattern case MUST have identities and evidence")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> PatternCase:
        evidence = value.get("evidence_refs")
        if not isinstance(evidence, Sequence) or isinstance(evidence, str | bytes):
            raise ValueError("pattern case evidence_refs MUST be an array")
        reusable = value.get("reusable")
        if not isinstance(reusable, bool):
            raise ValueError("pattern case reusable MUST be boolean")
        return cls(
            case_id=_required(value, "case_id"),
            action_type=_required(value, "action_type"),
            outcome_id=_required(value, "outcome_id"),
            reusable=reusable,
            evidence_refs=tuple(str(item) for item in evidence if str(item)),
        )


@dataclass(frozen=True, slots=True)
class OperatingPatternCandidate:
    pattern_id: str
    action_type: str
    sample_size: int
    reusable_count: int
    negative_count: int
    evidence_refs: tuple[str, ...]

    def to_rule_candidate_mapping(self) -> dict[str, object]:
        return {
            "source_signal": "operating_pattern_cohort",
            "evidence": {
                "sample_size": self.sample_size,
                "reusable_count": self.reusable_count,
                "negative_count": self.negative_count,
                "evidence_refs": list(self.evidence_refs),
            },
            "provenance": {"source": "case-history", "pattern_id": self.pattern_id},
            "proposed_by": "Norns",
            "proposal_kind": "new",
            "target_rule_id": self.action_type,
            "suggested_pattern": self.pattern_id,
        }


class OperatingPatternCompiler:
    """Require both positive and negative evidence before proposing a pattern."""

    def compile(self, cases: Sequence[PatternCase]) -> OperatingPatternCandidate | None:
        if len(cases) < 2:
            return None
        action_types = {case.action_type for case in cases}
        if len(action_types) != 1:
            return None
        reusable = sum(case.reusable for case in cases)
        negative = len(cases) - reusable
        if reusable < 1 or negative < 1:
            return None
        evidence = tuple(sorted({ref for case in cases for ref in case.evidence_refs}))
        material = {
            "action_type": cases[0].action_type,
            "case_ids": sorted(case.case_id for case in cases),
            "outcome_ids": sorted(case.outcome_id for case in cases),
        }
        pattern_id = hashlib.sha256(
            json.dumps(material, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        return OperatingPatternCandidate(
            pattern_id=pattern_id,
            action_type=cases[0].action_type,
            sample_size=len(cases),
            reusable_count=reusable,
            negative_count=negative,
            evidence_refs=evidence,
        )


def _required(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"pattern case field {key!r} MUST be non-empty")
    return item


__all__ = ["OperatingPatternCandidate", "OperatingPatternCompiler", "PatternCase"]
