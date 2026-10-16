"""ControlLoop persists bounded, content-free T1 shadow comparisons only when opted in."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pytest
from fdai.core.control_loop._boundary import ControlLoopBoundaryMixin
from fdai.core.tiers.t1_lightweight.tier import (
    SimilarityMatch,
    T1CandidateEligibility,
    T1Config,
    T1Decision,
    T1EligibilityComparison,
    T1Outcome,
)
from fdai.core.trust_router import RoutingDecision, RoutingTier
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from .test_contextual_reuse import _event
from .test_eligibility_comparison import _matches, _tier, _Verifications


class _AuditLoop(ControlLoopBoundaryMixin):
    def __init__(self, audit: InMemoryStateStore) -> None:
        self._audit_store = audit


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _identity(match: SimilarityMatch) -> str:
    action = match.action
    return _digest(
        json.dumps(
            (
                action.signature,
                action.rule_id,
                action.action_type,
                action.incident_id,
                action.operational_case.case_ref if action.operational_case is not None else None,
            ),
            ensure_ascii=True,
            separators=(",", ":"),
        )
    )


async def _audit(t1: T1Decision) -> dict[str, Any]:
    store = InMemoryStateStore()
    await _AuditLoop(store)._write_t1_audit(
        event=_event(),
        decision=RoutingDecision(tier=RoutingTier.T1, resource_type="kubernetes.service"),
        t1=t1,
    )
    entries = tuple(store.audit_entries)
    assert len(entries) == 1
    # Assert the appended record survives an ordinary JSON persistence boundary.
    row: object = json.loads(json.dumps(entries[0]["entry"]))
    assert isinstance(row, dict)
    return row


async def test_default_off_keeps_the_exact_existing_audit_shape() -> None:
    event = _event()
    row = await _audit(
        T1Decision(
            outcome=T1Outcome.ABSTAIN,
            event_id=str(event.event_id),
            threshold=0.8,
            reason="no_neighbour_found",
            reasons=("no_neighbour_found",),
        )
    )
    assert isinstance(row.pop("recorded_at"), str)
    assert row == {
        "event_id": str(event.event_id),
        "correlation_id": event.correlation_id or str(event.event_id),
        "idempotency_key": event.idempotency_key,
        "actor": "fdai.core.control_loop",
        "producer_principal": "Forseti",
        "action_kind": "control_loop.t1_evaluate",
        "mode": "shadow",
        "stage": "t1_similarity",
        "t1_outcome": "abstain",
        "t1_threshold": 0.8,
        "t1_reason": "no_neighbour_found",
        "t1_reasons": ["no_neighbour_found"],
        "t1_best_match": None,
        "t1_current_reuse_verification": None,
        "resource_type": "kubernetes.service",
    }


async def test_live_t1_comparison_is_persisted_without_changing_baseline_audit_fields() -> None:
    on, _, _ = _tier(verifier=_Verifications(top={"preconditions_passed": False}))
    off, _, _ = _tier(
        verifier=_Verifications(top={"preconditions_passed": False}),
        config=T1Config(compare_eligibility=False),
    )
    on_decision = await on.evaluate(event=_event())
    off_decision = await off.evaluate(event=_event())
    on_row, off_row = await _audit(on_decision), await _audit(off_decision)
    comparison = on_row.pop("t1_eligibility_comparison")
    on_row.pop("recorded_at")
    off_row.pop("recorded_at")
    assert on_row == off_row
    assert comparison["schema_version"] == "1.0.0"
    assert comparison["mode"] == "shadow"
    assert comparison["execution_authority"] is False
    assert comparison["promotion_authority"] is False
    assert comparison["actual_selection_changed"] is False
    first, second = _matches()
    assert comparison["baseline"]["outcome"] == "abstain"
    assert comparison["baseline"]["match_identity_digest"] == _identity(first)
    assert comparison["baseline"]["reasons"] == [
        {"code": "current_precondition_failed", "digest": _digest("current_precondition_failed")}
    ]
    assert comparison["challenger"]["outcome"] == "eligible"
    assert comparison["challenger"]["match_identity_digest"] == _identity(second)
    assert comparison["challenger"]["reasons"] == []
    assert comparison["checked_count"] == comparison["recorded_candidate_count"] == 2
    assert comparison["candidates_truncated"] is False
    assert [candidate["outcome"] for candidate in comparison["candidates"]] == [
        "ineligible",
        "eligible",
    ]
    assert comparison["stop_reason"] is None
    assert on_row["t1_outcome"] == "abstain"
    assert on_row["t1_current_reuse_verification"] is None


async def test_successful_baseline_has_the_same_digest_as_its_shadow_challenger() -> None:
    tier, _, verifier = _tier()
    t1 = await tier.evaluate(event=_event())
    row = await _audit(t1)
    comparison = row["t1_eligibility_comparison"]
    assert row["t1_outcome"] == "reused"
    assert comparison["baseline"]["outcome"] == "reused"
    assert comparison["challenger"]["outcome"] == "eligible"
    assert (
        comparison["baseline"]["match_identity_digest"]
        == comparison["challenger"]["match_identity_digest"]
    )
    assert comparison["checked_count"] == 1
    assert verifier.calls == ["top"]


async def test_global_policy_stop_persists_every_baseline_reason_without_fake_success() -> None:
    tier, _, _ = _tier(
        verifier=_Verifications(top={"preconditions_passed": False, "policy_allowed": False})
    )
    row = await _audit(await tier.evaluate(event=_event()))
    comparison = row["t1_eligibility_comparison"]
    assert comparison["baseline"]["reason_count"] == 2
    assert [reason["code"] for reason in comparison["baseline"]["reasons"]] == [
        "current_precondition_failed",
        "current_policy_denied",
    ]
    assert comparison["challenger"]["outcome"] == "stopped"
    assert comparison["challenger"]["match_identity_digest"] is None
    assert comparison["challenger"]["reasons"] == [comparison["stop_reason"]]
    assert comparison["stop_reason"]["code"] == "current_policy_denied"
    assert comparison["checked_count"] == 1
    assert row["t1_outcome"] == "abstain"


async def test_exhausted_candidates_record_no_selected_identity() -> None:
    tier, _, _ = _tier(
        verifier=_Verifications(
            top={"preconditions_passed": False}, next={"rollback_resolved": False}
        )
    )
    row = await _audit(await tier.evaluate(event=_event()))
    comparison = row["t1_eligibility_comparison"]
    assert comparison["challenger"]["outcome"] == "exhausted"
    assert comparison["challenger"]["match_identity_digest"] is None
    assert comparison["challenger"]["reasons"][0]["code"] == "historical_rollback_unresolved"
    assert comparison["stop_reason"] is None
    assert comparison["checked_count"] == 2


@pytest.mark.parametrize("stop_reason", ["t1_deadline_exceeded", "no_neighbour_found"])
async def test_stopped_comparison_with_no_checks_records_no_invented_eligibility(
    stop_reason: str,
) -> None:
    t1 = T1Decision(
        outcome=T1Outcome.ABSTAIN,
        event_id=str(_event().event_id),
        threshold=0.8,
        reason="no_neighbour_found",
        reasons=("no_neighbour_found",),
        eligibility_comparison=T1EligibilityComparison(
            baseline_outcome=T1Outcome.ABSTAIN,
            baseline_match=None,
            stop_reason=stop_reason,
        ),
    )
    comparison = (await _audit(t1))["t1_eligibility_comparison"]
    assert comparison["baseline"]["match_identity_digest"] is None
    assert comparison["challenger"]["outcome"] == "stopped"
    assert comparison["challenger"]["match_identity_digest"] is None
    assert comparison["checked_count"] == comparison["recorded_candidate_count"] == 0
    assert comparison["candidates"] == []
    assert comparison["stop_reason"]["code"] == stop_reason


async def test_challenger_identifiers_parameters_and_arbitrary_reasons_never_leak() -> None:
    sensitive = "example-private-target-and-parameter-" + "x" * 1000
    first, second = _matches()
    second = replace(
        second,
        action=replace(
            second.action,
            signature=sensitive,
            rule_id=sensitive,
            action_type=sensitive,
            incident_id=sensitive,
            params={"target": sensitive, "parameter": {"nested": sensitive}},
        ),
    )
    t1 = T1Decision(
        outcome=T1Outcome.ABSTAIN,
        event_id=str(_event().event_id),
        threshold=0.8,
        best_match=first,
        reason="current_precondition_failed",
        reasons=("current_precondition_failed",),
        eligibility_comparison=T1EligibilityComparison(
            baseline_outcome=T1Outcome.ABSTAIN,
            baseline_match=first,
            candidates=(
                T1CandidateEligibility(
                    match=second,
                    eligible=False,
                    reasons=(sensitive, "current_reuse_verification_error:" + sensitive),
                ),
            ),
            stop_reason=sensitive,
        ),
    )
    row = await _audit(t1)
    comparison = row["t1_eligibility_comparison"]
    assert sensitive not in json.dumps(row)
    candidate = comparison["candidates"][0]
    assert candidate["match_identity_digest"] == _identity(second)
    assert candidate["reasons"] == [
        {"code": "redacted", "digest": _digest(sensitive)},
        {
            "code": "current_reuse_verification_error",
            "digest": _digest("current_reuse_verification_error:" + sensitive),
        },
    ]
    assert comparison["stop_reason"] == {"code": "redacted", "digest": _digest(sensitive)}
    assert set(candidate) == {
        "outcome",
        "match_identity_digest",
        "reasons",
        "reason_count",
        "reasons_truncated",
    }


async def test_audit_collections_are_bounded_and_truncation_is_explicit() -> None:
    first, _ = _matches()
    reasons = ("current_precondition_failed",) * 40
    t1 = T1Decision(
        outcome=T1Outcome.ABSTAIN,
        event_id=str(_event().event_id),
        threshold=0.8,
        best_match=first,
        reason=reasons[0],
        reasons=reasons,
        eligibility_comparison=T1EligibilityComparison(
            baseline_outcome=T1Outcome.ABSTAIN,
            baseline_match=first,
            candidates=(T1CandidateEligibility(match=first, eligible=False, reasons=reasons),) * 8,
        ),
    )
    comparison = (await _audit(t1))["t1_eligibility_comparison"]
    assert comparison["checked_count"] == 8
    assert comparison["recorded_candidate_count"] == len(comparison["candidates"]) == 5
    assert comparison["candidates_truncated"] is True
    for outcome in [comparison["baseline"], comparison["challenger"], *comparison["candidates"]]:
        assert len(outcome["reasons"]) == 32
        assert outcome["reason_count"] == 40
        assert outcome["reasons_truncated"] is True


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        ("similarity=0.7000<threshold=0.8000", "similarity_below_threshold"),
        ("success_rate=0.5000<floor=0.9000", "success_rate_below_floor"),
        ("t1_provider_error:RuntimeError", "t1_provider_error"),
        ("t1_candidate_error:AttributeError", "t1_candidate_error"),
        ("unrecognized-provider-diagnostic", "redacted"),
    ],
)
async def test_dynamic_diagnostics_have_safe_codes_and_exact_digest_identity(
    reason: str, code: str
) -> None:
    tier, _, _ = _tier()
    t1 = await tier.evaluate(event=_event())
    assert t1.eligibility_comparison is not None
    t1 = replace(
        t1,
        eligibility_comparison=replace(
            t1.eligibility_comparison, challenger_match=None, stop_reason=reason
        ),
    )
    comparison = (await _audit(t1))["t1_eligibility_comparison"]
    assert comparison["stop_reason"] == {"code": code, "digest": _digest(reason)}


async def test_audit_append_failure_is_not_reported_as_persisted_comparison() -> None:
    class _UnavailableAudit(InMemoryStateStore):
        async def append_audit_entry(self, entry: Mapping[str, Any]) -> None:
            raise OSError("audit unavailable")

    tier, _, _ = _tier()
    t1 = await tier.evaluate(event=_event())
    audit = _UnavailableAudit()
    with pytest.raises(OSError, match="audit unavailable"):
        await _AuditLoop(audit)._write_t1_audit(
            event=_event(),
            decision=RoutingDecision(tier=RoutingTier.T1, resource_type="kubernetes.service"),
            t1=t1,
        )
    assert audit.audit_entries == ()
