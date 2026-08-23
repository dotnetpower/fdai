"""Reusable operational catalog candidate fixture for focused tests."""

from __future__ import annotations

from fdai.core.case_history import OperationalOutcomeClass
from fdai.core.operational_learning import OperatingPatternCompiler, PatternCase


def operational_candidate_mapping() -> dict[str, object]:
    """Return one balanced, consensus-approved operational Rule candidate."""
    cases = (
        PatternCase(
            case_id="case-success",
            revision=1,
            manifest_digest="1" * 64,
            failure_fingerprint="2" * 64,
            resource_type="kubernetes.service",
            action_type="ops.scale-out",
            outcome_class=OperationalOutcomeClass.SUCCESS,
            reusable=True,
            negative=False,
            digest_evidence=("3" * 64,),
        ),
        PatternCase(
            case_id="case-rollback",
            revision=1,
            manifest_digest="4" * 64,
            failure_fingerprint="2" * 64,
            resource_type="kubernetes.service",
            action_type="ops.scale-out",
            outcome_class=OperationalOutcomeClass.ROLLBACK,
            reusable=False,
            negative=True,
            digest_evidence=("5" * 64,),
        ),
    )
    candidate = OperatingPatternCompiler().compile(cases)
    if candidate is None:
        raise AssertionError("balanced fixture MUST compile")
    return {
        "producer_principal": "Norns",
        "norns_consensus": {
            "decision": "propose",
            "unanimous": True,
            "perspective_count": 3,
            "reason_codes": [
                "historical_evidence_grounded",
                "current_contract_valid",
                "future_safety_preserved",
            ],
        },
        **candidate.to_rule_candidate_mapping(),
    }


__all__ = ["operational_candidate_mapping"]
