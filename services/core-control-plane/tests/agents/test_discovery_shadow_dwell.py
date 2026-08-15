"""Discovery-loop shadow dwell - Norns retains it, Mimir refuses without it.

Role restatement (agent-pantheon.instructions.md 2):

- **Norns** (governance, Learner) owns ``RuleCandidate`` / ``PatternObservation``,
  publishes ``object.rule-candidate``, subscribes to ``object.audit-entry`` among
  others, uses an LLM off-path only, and is not a hard dependency. Nothing here
  changes that: the dwell ledger is fed from the audit-entry subscription it
  already has, and the evidence rides the candidate it already publishes.
- **Mimir** (governance, Rule Steward) owns ``Rule`` / ``Policy``, subscribes to
  ``object.rule-candidate``, and never executes. The gate added here only makes
  Mimir refuse more; it grants no new authority and mutates no catalog.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.agents.mimir import Mimir
from fdai.agents.norns import Norns
from fdai.core.operational_learning import ShadowDwellThresholds

_START = datetime(2026, 1, 1, tzinfo=UTC)
_TARGET = "remediate.enable-tde"
_THRESHOLDS = ShadowDwellThresholds(min_shadow_days=14, min_samples=100, min_accuracy=0.98)


def _shadow_audit(index: int, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action_type": _TARGET,
        "shadow_mode": True,
        "result": "success",
        "correlation_id": f"shadow-{index}",
        "observed_at": (_START + timedelta(days=index * 0.2)).isoformat(),
        "operator_reviewed": True,
        "operator_agreed": True,
        "policy_escape": False,
    }
    payload.update(overrides)
    return payload


def _feed_shadow(norns: Norns, count: int, **overrides: Any) -> None:
    for index in range(count):
        asyncio.run(norns.on_typed_message("object.audit-entry", _shadow_audit(index, **overrides)))


def _candidate(dwell: dict[str, Any] | None) -> dict[str, Any]:
    candidate: dict[str, Any] = {
        "idempotency_key": f"candidate:{_TARGET}:1",
        "correlation_id": "corr-dwell",
        "target_rule_id": _TARGET,
        "proposal_kind": "revision",
        "proposed_by": "Norns",
        "source_signal": "audit_outcome",
        "evidence": {"target": _TARGET, "sample_size": 120, "rollback_rate": 0.3},
    }
    if dwell is not None:
        candidate["shadow_dwell"] = dwell
    return candidate


def _sufficient_dwell(**overrides: Any) -> dict[str, Any]:
    dwell: dict[str, Any] = {
        "target": _TARGET,
        "window_start": _START.isoformat(),
        "window_end": (_START + timedelta(days=20)).isoformat(),
        "sample_size": 120,
        "reviewed_count": 120,
        "agreed_count": 120,
        "policy_escapes": 0,
    }
    dwell.update(overrides)
    return dwell


def _mimir_with(candidate: dict[str, Any]) -> Mimir:
    mimir = Mimir(shadow_dwell_thresholds=_THRESHOLDS)
    asyncio.run(mimir.on_typed_message("object.rule-candidate", candidate))
    assert len(mimir.pending_candidates()) == 1, "guard must accept this candidate"
    return mimir


# ---------------------------------------------------------------------------
# Norns retains shadow dwell evidence
# ---------------------------------------------------------------------------


def test_norns_retains_shadow_outcomes_as_dwell_evidence() -> None:
    norns = Norns()
    _feed_shadow(norns, 30)

    evidence = norns.shadow_dwell_evidence(_TARGET)
    assert evidence is not None
    assert evidence.sample_size == 30
    assert evidence.reviewed_count == 30
    assert evidence.accuracy == pytest.approx(1.0)
    assert evidence.policy_escapes == 0


def test_shadow_outcomes_still_never_dilute_the_rollback_learner() -> None:
    """Retaining dwell evidence MUST NOT turn shadow successes into safety evidence."""
    norns = Norns(min_outcome_samples=5, rollback_alarm_rate=0.2)
    _feed_shadow(norns, 30)

    assert norns.outcome_rate(_TARGET) is None
    assert norns.pending_candidates == []


def test_replayed_shadow_audit_does_not_inflate_the_sample() -> None:
    norns = Norns()
    for _ in range(4):
        asyncio.run(norns.on_typed_message("object.audit-entry", _shadow_audit(0)))

    evidence = norns.shadow_dwell_evidence(_TARGET)
    assert evidence is not None
    assert evidence.sample_size == 1


def test_untimed_shadow_audit_is_not_retained() -> None:
    """Without an instant there is no window, so the observation is dropped."""
    norns = Norns()
    asyncio.run(norns.on_typed_message("object.audit-entry", _shadow_audit(0, observed_at=None)))

    assert norns.shadow_dwell_evidence(_TARGET) is None
    assert norns.behavior_snapshot()["shadow_dwell_observation_untimed"] == 1


def test_naive_instant_is_not_retained() -> None:
    norns = Norns()
    asyncio.run(
        norns.on_typed_message(
            "object.audit-entry",
            _shadow_audit(0, observed_at="2026-01-01T00:00:00"),
        )
    )
    assert norns.shadow_dwell_evidence(_TARGET) is None


def test_non_boolean_review_flags_are_not_retained() -> None:
    norns = Norns()
    asyncio.run(
        norns.on_typed_message("object.audit-entry", _shadow_audit(0, operator_reviewed="yes"))
    )
    assert norns.shadow_dwell_evidence(_TARGET) is None
    assert norns.behavior_snapshot()["shadow_dwell_observation_invalid"] == 1


def test_unreviewed_shadow_traffic_cannot_claim_agreement() -> None:
    norns = Norns()
    _feed_shadow(norns, 10, operator_reviewed=False, operator_agreed=True)

    evidence = norns.shadow_dwell_evidence(_TARGET)
    assert evidence is not None
    assert evidence.reviewed_count == 0
    assert evidence.agreed_count == 0
    assert evidence.accuracy == 0.0


def test_shadow_policy_escape_is_recorded() -> None:
    norns = Norns()
    _feed_shadow(norns, 5)
    asyncio.run(norns.on_typed_message("object.audit-entry", _shadow_audit(99, policy_escape=True)))

    evidence = norns.shadow_dwell_evidence(_TARGET)
    assert evidence is not None
    assert evidence.policy_escapes == 1


def test_published_candidate_carries_its_dwell_evidence() -> None:
    norns = Norns(rejection_revise_threshold=2)
    _feed_shadow(norns, 20)
    for index in range(2):
        asyncio.run(
            norns.on_typed_message(
                "object.approval",
                {
                    "action_type": _TARGET,
                    "state": "rejected",
                    "correlation_id": f"hil-{index}",
                },
            )
        )

    assert len(norns.pending_candidates) == 1
    published: list[dict[str, Any]] = []

    class _Recorder:
        async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
            published.append(payload)

    norns.bind_bus(_Recorder())  # type: ignore[arg-type]
    asyncio.run(norns.flush_candidates())

    assert len(published) == 1
    assert published[0]["shadow_dwell"]["target"] == _TARGET
    assert published[0]["shadow_dwell"]["sample_size"] == 20


# ---------------------------------------------------------------------------
# Mimir refuses without sufficient evidence
# ---------------------------------------------------------------------------


def test_candidate_without_dwell_evidence_is_not_promotion_ready() -> None:
    mimir = _mimir_with(_candidate(None))
    assert mimir.promotion_ready_candidates() == ()
    assert mimir.shadow_dwell_decision(mimir.pending_candidates()[0]).gaps == (
        "no_shadow_dwell_evidence",
    )


def test_candidate_with_sufficient_dwell_is_promotion_ready() -> None:
    mimir = _mimir_with(_candidate(_sufficient_dwell()))
    assert len(mimir.promotion_ready_candidates()) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"window_end": (_START + timedelta(days=3)).isoformat()},
        {"sample_size": 40, "reviewed_count": 40, "agreed_count": 40},
        {"reviewed_count": 0, "agreed_count": 0},
        {"agreed_count": 100},
        {"policy_escapes": 1},
    ],
    ids=["short-window", "thin-sample", "unreviewed", "inaccurate", "one-escape"],
)
def test_under_threshold_candidate_never_reaches_the_promotion_list(
    overrides: dict[str, Any],
) -> None:
    mimir = _mimir_with(_candidate(_sufficient_dwell(**overrides)))
    assert mimir.promotion_ready_candidates() == ()


def test_forged_dwell_evidence_is_rejected_not_trusted() -> None:
    mimir = _mimir_with(_candidate(_sufficient_dwell(agreed_count=99_999)))
    decision = mimir.shadow_dwell_decision(mimir.pending_candidates()[0])
    assert decision.eligible is False
    assert decision.gaps[0].startswith("shadow_dwell_evidence_invalid:")


def test_dwell_evidence_borrowed_from_another_rule_is_rejected() -> None:
    """A clean record belongs to the rule that earned it."""
    mimir = _mimir_with(_candidate(_sufficient_dwell(target="remediate.enable-rbac")))
    decision = mimir.shadow_dwell_decision(mimir.pending_candidates()[0])
    assert decision.gaps == ("shadow_dwell_target_mismatch",)


def test_non_mapping_dwell_evidence_is_rejected() -> None:
    mimir = _mimir_with(_candidate(None) | {"shadow_dwell": "vouched"})
    decision = mimir.shadow_dwell_decision(mimir.pending_candidates()[0])
    assert decision.gaps == ("shadow_dwell_evidence_invalid:evidence_schema_invalid",)


def test_promote_refuses_a_rule_whose_pending_candidate_lacks_dwell() -> None:
    mimir = _mimir_with(_candidate(None))
    with pytest.raises(ValueError, match="shadow dwell evidence is insufficient"):
        mimir.promote(_TARGET, source="handoff")
    assert mimir.status(_TARGET) is None


def test_promote_refuses_an_under_threshold_candidate() -> None:
    mimir = _mimir_with(_candidate(_sufficient_dwell(policy_escapes=1)))
    with pytest.raises(ValueError, match="policy_escapes=1"):
        mimir.promote(_TARGET, source="handoff")


def test_promote_succeeds_once_the_dwell_is_proven() -> None:
    mimir = _mimir_with(_candidate(_sufficient_dwell()))
    promotion = mimir.promote(_TARGET, source="handoff")
    assert promotion.state == "enforce"
    assert mimir.pending_candidates() == ()


def test_promote_is_unaffected_for_a_rule_with_no_pending_candidate() -> None:
    """The dwell gate guards the discovery loop, not every steward decision."""
    mimir = Mimir(shadow_dwell_thresholds=_THRESHOLDS)
    assert mimir.promote("unrelated.rule", source="manual").state == "enforce"


def test_end_to_end_shadow_dwell_closes_the_loop() -> None:
    """Norns observes shadow traffic, publishes, and Mimir accepts only then."""
    norns = Norns(rejection_revise_threshold=2)
    mimir = Mimir(shadow_dwell_thresholds=ShadowDwellThresholds(min_samples=100))
    published: list[dict[str, Any]] = []

    class _Bridge:
        async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
            published.append(payload)
            await mimir.on_typed_message(topic, payload)

    norns.bind_bus(_Bridge())  # type: ignore[arg-type]
    _feed_shadow(norns, 120)
    for index in range(2):
        asyncio.run(
            norns.on_typed_message(
                "object.approval",
                {"action_type": _TARGET, "state": "rejected", "correlation_id": f"hil-{index}"},
            )
        )

    assert len(published) == 1
    assert len(mimir.promotion_ready_candidates()) == 1
    assert mimir.promote(_TARGET, source="handoff").state == "enforce"
