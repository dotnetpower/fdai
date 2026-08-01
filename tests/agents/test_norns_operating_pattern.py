from __future__ import annotations

from typing import Any, cast

from fdai.agents import Norns, instantiate_pantheon
from fdai.core.case_history import OperationalOutcomeClass


def _case(
    identifier: str,
    *,
    outcome_class: OperationalOutcomeClass,
) -> dict[str, object]:
    reusable = outcome_class is OperationalOutcomeClass.SUCCESS
    return {
        "case_id": f"case-{identifier}",
        "revision": 1,
        "manifest_digest": identifier[0] * 64,
        "failure_fingerprint": "f" * 64,
        "resource_type": "kubernetes.service",
        "action_type": "ops.scale-out",
        "outcome_class": outcome_class.value,
        "reusable": reusable,
        "negative": not reusable,
        "digest_evidence": ["e" * 64],
    }


def _payload(*cases: dict[str, object]) -> dict[str, object]:
    return {
        "producer_principal": "Muninn",
        "kind": "operational_case_fingerprint_cohort",
        "failure_fingerprint": "f" * 64,
        "cases": list(cases),
    }


async def test_success_only_operating_cohort_is_held() -> None:
    norns = Norns()

    await norns.on_typed_message(
        "object.context-index",
        _payload(
            _case("a-one", outcome_class=OperationalOutcomeClass.SUCCESS),
            _case("b-two", outcome_class=OperationalOutcomeClass.SUCCESS),
        ),
    )

    assert norns.pending_candidates == []


async def test_balanced_operating_cohort_reaches_mimir_guard() -> None:
    norns = Norns()
    mimir = cast(Any, instantiate_pantheon()["Mimir"])

    await norns.on_typed_message(
        "object.context-index",
        _payload(
            _case("a-success", outcome_class=OperationalOutcomeClass.SUCCESS),
            _case("b-control", outcome_class=OperationalOutcomeClass.ROLLBACK),
        ),
    )

    assert len(norns.pending_candidates) == 1
    candidate = norns.pending_candidates[0]
    await mimir.on_typed_message(
        "object.rule-candidate",
        {
            "producer_principal": "Norns",
            "correlation_id": "norns:operating-pattern",
            "idempotency_key": "rule-candidate:operating-pattern",
            **candidate,
            "norns_consensus": {
                "decision": "propose",
                "unanimous": True,
                "perspective_count": 3,
            },
        },
    )

    assert len(mimir.pending_candidates()) == 1
    assert mimir.pending_candidates()[0]["source_signal"] == "operational_case_fingerprint_cohort"


async def test_replayed_operating_cohort_emits_one_candidate() -> None:
    norns = Norns()
    payload = _payload(
        _case("a-success", outcome_class=OperationalOutcomeClass.SUCCESS),
        _case("b-control", outcome_class=OperationalOutcomeClass.ROLLBACK),
    )

    await norns.on_typed_message("object.context-index", payload)
    await norns.on_typed_message("object.context-index", payload)

    assert len(norns.pending_candidates) == 1
    assert norns.behavior_snapshot()["operational_case_cohort_duplicate"] == 1
