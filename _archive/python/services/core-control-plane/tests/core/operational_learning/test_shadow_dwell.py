"""Shadow dwell evidence - the discovery loop's fail-closed promotion bar.

Every test here tries to get an under-evidenced candidate past the gate. The gate
is only worth having if each of these attempts fails.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.operational_learning.shadow_dwell import (
    ShadowDwellDecision,
    ShadowDwellEvidence,
    ShadowDwellEvidenceError,
    ShadowDwellLedger,
    ShadowDwellObservation,
    ShadowDwellThresholds,
    evaluate_shadow_dwell,
)

_START = datetime(2026, 1, 1, tzinfo=UTC)
_THRESHOLDS = ShadowDwellThresholds(min_shadow_days=14, min_samples=100, min_accuracy=0.98)


def _evidence(**overrides: object) -> ShadowDwellEvidence:
    base: dict[str, object] = {
        "target": "remediate.enable-tde",
        "window_start": _START,
        "window_end": _START + timedelta(days=20),
        "sample_size": 120,
        "reviewed_count": 120,
        "agreed_count": 120,
        "policy_escapes": 0,
    }
    base.update(overrides)
    return ShadowDwellEvidence(**base)  # type: ignore[arg-type]


def _observation(offset_days: float, **overrides: object) -> ShadowDwellObservation:
    base: dict[str, object] = {
        "target": "remediate.enable-tde",
        "observed_at": _START + timedelta(days=offset_days),
        "reviewed": True,
        "agreed": True,
        "policy_escape": False,
    }
    base.update(overrides)
    return ShadowDwellObservation(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Fail-closed evaluation
# ---------------------------------------------------------------------------


def test_absent_evidence_is_not_consent() -> None:
    """A candidate nobody ever watched in shadow MUST NOT pass by omission."""
    decision = evaluate_shadow_dwell(None, _THRESHOLDS)
    assert decision.eligible is False
    assert decision.gaps == ("no_shadow_dwell_evidence",)


def test_sufficient_evidence_is_eligible() -> None:
    decision = evaluate_shadow_dwell(_evidence(), _THRESHOLDS)
    assert decision.eligible is True
    assert decision.gaps == ()


def test_short_window_is_ineligible() -> None:
    evidence = _evidence(window_end=_START + timedelta(days=13, hours=23))
    decision = evaluate_shadow_dwell(evidence, _THRESHOLDS)
    assert decision.eligible is False
    assert any(gap.startswith("shadow_days=") for gap in decision.gaps)


def test_a_narrow_window_gap_never_reports_the_threshold_itself() -> None:
    """A rounded report reads as "14.00<14" and looks like a bug in the gate."""
    evidence = _evidence(window_end=_START + timedelta(days=14) - timedelta(seconds=1))
    decision = evaluate_shadow_dwell(evidence, _THRESHOLDS)
    assert decision.eligible is False
    assert "shadow_days=13.99<min_shadow_days=14" in decision.gaps


def test_thin_sample_is_ineligible() -> None:
    evidence = _evidence(sample_size=99, reviewed_count=99, agreed_count=99)
    decision = evaluate_shadow_dwell(evidence, _THRESHOLDS)
    assert decision.eligible is False
    assert any(gap.startswith("sample_size=") for gap in decision.gaps)


def test_unreviewed_samples_are_ineligible() -> None:
    """Volume without human review is not accuracy evidence."""
    evidence = _evidence(reviewed_count=0, agreed_count=0)
    decision = evaluate_shadow_dwell(evidence, _THRESHOLDS)
    assert decision.eligible is False
    assert "no_reviewed_samples" in decision.gaps


def test_accuracy_below_threshold_is_ineligible() -> None:
    evidence = _evidence(agreed_count=117)
    decision = evaluate_shadow_dwell(evidence, _THRESHOLDS)
    assert decision.eligible is False
    assert any(gap.startswith("accuracy=") for gap in decision.gaps)


def test_single_policy_escape_is_ineligible() -> None:
    """The design says zero escapes, so exactly one escape MUST block promotion."""
    decision = evaluate_shadow_dwell(_evidence(policy_escapes=1), _THRESHOLDS)
    assert decision.eligible is False
    assert any(gap.startswith("policy_escapes=") for gap in decision.gaps)


def test_every_unmet_bar_is_reported() -> None:
    evidence = _evidence(
        window_end=_START + timedelta(days=1),
        sample_size=4,
        reviewed_count=4,
        agreed_count=1,
        policy_escapes=2,
    )
    decision = evaluate_shadow_dwell(evidence, _THRESHOLDS)
    assert decision.eligible is False
    assert len(decision.gaps) == 4


def test_decision_cannot_claim_eligibility_with_gaps() -> None:
    with pytest.raises(ValueError, match="eligible exactly when no gap"):
        ShadowDwellDecision(eligible=True, gaps=("no_shadow_dwell_evidence",))


# ---------------------------------------------------------------------------
# Self-verifying evidence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"window_end": _START - timedelta(days=1)}, "window_inverted"),
        ({"sample_size": -1}, "count_invalid:sample_size"),
        ({"reviewed_count": 121}, "count_conflict:reviewed_count"),
        ({"agreed_count": 121}, "count_conflict:agreed_count"),
        ({"policy_escapes": 121}, "count_conflict:policy_escapes"),
        ({"target": "Not An Identifier"}, "target_invalid"),
        ({"window_start": datetime(2026, 1, 1)}, "instant_invalid:window_start"),  # noqa: DTZ001
    ],
)
def test_inconsistent_evidence_is_rejected(overrides: dict[str, object], code: str) -> None:
    """Evidence arrives over the wire, so it MUST NOT be trusted at face value."""
    with pytest.raises(ShadowDwellEvidenceError) as excinfo:
        _evidence(**overrides)
    assert excinfo.value.code == code


def test_accuracy_cannot_exceed_one_by_construction() -> None:
    with pytest.raises(ShadowDwellEvidenceError):
        _evidence(reviewed_count=10, agreed_count=11)


def test_mapping_round_trip_preserves_evidence() -> None:
    evidence = _evidence()
    restored = ShadowDwellEvidence.from_mapping(evidence.to_mapping())
    assert restored == evidence


@pytest.mark.parametrize(
    "payload",
    [
        "not-a-mapping",
        {},
        {"target": "remediate.enable-tde"},
    ],
)
def test_malformed_mapping_is_rejected(payload: object) -> None:
    with pytest.raises(ShadowDwellEvidenceError) as excinfo:
        ShadowDwellEvidence.from_mapping(payload)
    assert excinfo.value.code == "evidence_schema_invalid"


def test_extra_mapping_keys_are_rejected() -> None:
    """An unknown key means the sender and the gate disagree about the contract."""
    payload = _evidence().to_mapping() | {"vouched_by": "model"}
    with pytest.raises(ShadowDwellEvidenceError):
        ShadowDwellEvidence.from_mapping(payload)


def test_boolean_counts_are_rejected() -> None:
    payload = _evidence().to_mapping() | {"sample_size": True}
    with pytest.raises(ShadowDwellEvidenceError) as excinfo:
        ShadowDwellEvidence.from_mapping(payload)
    assert excinfo.value.code == "count_invalid:sample_size"


def test_naive_instant_in_mapping_is_rejected() -> None:
    payload = _evidence().to_mapping() | {"window_end": "2026-01-21T00:00:00"}
    with pytest.raises(ShadowDwellEvidenceError) as excinfo:
        ShadowDwellEvidence.from_mapping(payload)
    assert excinfo.value.code == "instant_invalid:window_end"


def test_thresholds_reject_impossible_configuration() -> None:
    with pytest.raises(ValueError, match="at least one day and sample"):
        ShadowDwellThresholds(min_shadow_days=0)
    with pytest.raises(ValueError, match="min_accuracy"):
        ShadowDwellThresholds(min_accuracy=0.0)


def test_agreement_without_review_is_rejected() -> None:
    with pytest.raises(ShadowDwellEvidenceError) as excinfo:
        _observation(0.0, reviewed=False, agreed=True)
    assert excinfo.value.code == "observation_agreement_unreviewed"


# ---------------------------------------------------------------------------
# Ledger retention
# ---------------------------------------------------------------------------


def test_ledger_returns_no_evidence_for_unobserved_target() -> None:
    assert ShadowDwellLedger().evidence_for("remediate.enable-tde") is None


def test_ledger_aggregates_window_samples_accuracy_and_escapes() -> None:
    ledger = ShadowDwellLedger()
    for index in range(20):
        ledger.record(_observation(index))
    ledger.record(_observation(20, agreed=False))
    ledger.record(_observation(21, reviewed=False, agreed=False, policy_escape=True))

    evidence = ledger.evidence_for("remediate.enable-tde")
    assert evidence is not None
    assert evidence.sample_size == 22
    assert evidence.reviewed_count == 21
    assert evidence.agreed_count == 20
    assert evidence.policy_escapes == 1
    assert evidence.shadow_days == pytest.approx(21.0)
    assert evidence.accuracy == pytest.approx(20 / 21)


def test_ledger_keeps_targets_separate() -> None:
    """One rule's clean record MUST NOT vouch for another rule."""
    ledger = ShadowDwellLedger()
    for index in range(30):
        ledger.record(_observation(index))
    ledger.record(_observation(0, target="remediate.enable-rbac"))

    clean = ledger.evidence_for("remediate.enable-tde")
    sparse = ledger.evidence_for("remediate.enable-rbac")
    assert clean is not None and sparse is not None
    assert clean.sample_size == 30
    assert sparse.sample_size == 1
    assert evaluate_shadow_dwell(sparse, _THRESHOLDS).eligible is False


def test_ledger_bounds_observations_per_target() -> None:
    ledger = ShadowDwellLedger(max_observations_per_target=5)
    for index in range(50):
        ledger.record(_observation(index))
    assert ledger.observation_count("remediate.enable-tde") == 5
    evidence = ledger.evidence_for("remediate.enable-tde")
    assert evidence is not None
    # Retention bounds the observation detail, never the counted evidence.
    assert evidence.sample_size == 50


def test_bounded_retention_never_forgets_a_policy_escape() -> None:
    """Zero escapes is not a setting, so eviction must not re-admit an escaped target."""
    ledger = ShadowDwellLedger(max_observations_per_target=5)
    ledger.record(_observation(0, policy_escape=True))
    for index in range(1, 50):
        ledger.record(_observation(index))

    evidence = ledger.evidence_for("remediate.enable-tde")

    assert evidence is not None
    assert evidence.policy_escapes == 1
    assert evaluate_shadow_dwell(evidence, _THRESHOLDS).eligible is False


def test_target_churn_never_evicts_the_only_policy_escape_evidence() -> None:
    ledger = ShadowDwellLedger(max_targets=1, max_observations_per_target=2)
    ledger.record(_observation(0, target="rule.escaped", policy_escape=True))

    with pytest.raises(
        ShadowDwellEvidenceError,
        match="target_capacity_exhausted_by_escaped_evidence",
    ):
        ledger.record(_observation(1, target="rule.new"))

    escaped = ledger.evidence_for("rule.escaped")
    assert escaped is not None
    assert escaped.policy_escapes == 1
    assert ledger.evidence_for("rule.new") is None
    assert evaluate_shadow_dwell(escaped, _THRESHOLDS).eligible is False


def test_ledger_bounds_tracked_targets() -> None:
    ledger = ShadowDwellLedger(max_targets=2)
    for index in range(5):
        ledger.record(_observation(0, target=f"remediate.rule-{index}"))
    assert ledger.targets() == ("remediate.rule-3", "remediate.rule-4")


def test_ledger_rejects_foreign_observation_types() -> None:
    with pytest.raises(TypeError, match="ShadowDwellObservation"):
        ShadowDwellLedger().record({"target": "remediate.enable-tde"})  # type: ignore[arg-type]
