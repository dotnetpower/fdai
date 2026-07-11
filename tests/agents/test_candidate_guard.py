"""CandidateGuard - provenance + poisoning defense for the discovery loop.

Covers the grounded-provenance MUST and the data-poisoning defenses:
required proposal_kind/proposed_by/evidence, numeric range sanity, and
flood detection for repeated identical fingerprints.
"""

from __future__ import annotations

import pytest

from fdai.agents._framework.candidate_guard import CandidateGuard


def _valid() -> dict[str, object]:
    return {
        "proposed_by": "Norns",
        "proposal_kind": "threshold_adjustment",
        "target_rule_id": "remediate.x",
        "source_signal": "audit_outcome",
        "evidence": {"sample_size": 20, "rollback_rate": 0.4},
    }


def test_valid_candidate_accepted() -> None:
    guard = CandidateGuard()
    verdict = guard.inspect(_valid())
    assert verdict.accepted is True
    assert verdict.reason == "ok"


def test_unknown_proposal_kind_rejected() -> None:
    guard = CandidateGuard()
    c = _valid() | {"proposal_kind": "sabotage"}
    assert guard.inspect(c).reason == "unknown_proposal_kind:sabotage"


def test_missing_provenance_rejected() -> None:
    guard = CandidateGuard()
    c = _valid()
    del c["proposed_by"]
    assert guard.inspect(c).reason == "missing_provenance:proposed_by"


def test_ungrounded_rejected() -> None:
    guard = CandidateGuard()
    c = _valid() | {"evidence": {}}
    assert guard.inspect(c).reason == "ungrounded:no_evidence"


def test_out_of_range_rollback_rate_rejected() -> None:
    guard = CandidateGuard()
    c = _valid() | {"evidence": {"sample_size": 20, "rollback_rate": 1.7}}
    assert guard.inspect(c).reason == "evidence_out_of_range:rollback_rate"


def test_non_positive_count_rejected() -> None:
    guard = CandidateGuard()
    c = _valid() | {"evidence": {"sample_size": 0}}
    assert guard.inspect(c).reason == "evidence_out_of_range:sample_size"


def test_bool_count_rejected() -> None:
    """A bool sneaking in as a count is rejected (bool is an int subclass)."""
    guard = CandidateGuard()
    c = _valid() | {"evidence": {"occurrence_count": True}}
    assert guard.inspect(c).reason == "evidence_out_of_range:occurrence_count"


def test_flood_detection_quarantines_repeats() -> None:
    guard = CandidateGuard(max_repeats=3)
    c = _valid()
    # First three identical fingerprints accepted, fourth quarantined.
    assert guard.inspect(c).accepted is True
    assert guard.inspect(c).accepted is True
    assert guard.inspect(c).accepted is True
    flooded = guard.inspect(c)
    assert flooded.accepted is False
    assert flooded.reason == "flood_suspected"


def test_distinct_fingerprints_not_flooded() -> None:
    guard = CandidateGuard(max_repeats=1)
    assert guard.inspect(_valid() | {"target_rule_id": "a"}).accepted is True
    assert guard.inspect(_valid() | {"target_rule_id": "b"}).accepted is True


def test_flood_counter_map_is_bounded() -> None:
    # The guard's own repeat-counter must be bounded: an attacker sending
    # candidates with ever-changing fingerprints would otherwise grow it
    # without limit (a DoS via the poisoning defense itself).
    from fdai.agents._framework.candidate_guard import _MAX_FINGERPRINTS

    guard = CandidateGuard()
    for i in range(_MAX_FINGERPRINTS + 100):
        guard.inspect(_valid() | {"target_rule_id": f"r{i}"})
    assert len(guard._seen) == _MAX_FINGERPRINTS  # noqa: SLF001


def test_flood_detection_survives_bounded_counter() -> None:
    # A genuine flood REPEATS one fingerprint, keeping it most-recently-used,
    # so it is never evicted mid-burst - flood detection still fires even
    # while distinct fingerprints churn through the bounded map.
    guard = CandidateGuard(max_repeats=3)
    target = _valid() | {"target_rule_id": "victim"}
    for _ in range(3):
        assert guard.inspect(target).accepted is True
    assert guard.inspect(target).reason == "flood_suspected"


def test_invalid_config_rejected() -> None:
    with pytest.raises(ValueError, match="max_repeats"):
        CandidateGuard(max_repeats=0)


def test_non_finite_count_evidence_is_quarantined() -> None:
    """NaN / inf in a positive-count field is a corrupt/forged signal."""
    guard = CandidateGuard()
    nan_candidate = _valid() | {"evidence": {"sample_size": float("nan")}}
    assert guard.inspect(nan_candidate).accepted is False
    inf_candidate = _valid() | {"evidence": {"occurrence_count": float("inf")}}
    assert guard.inspect(inf_candidate).accepted is False


def test_non_finite_rollback_rate_is_quarantined() -> None:
    guard = CandidateGuard()
    candidate = _valid() | {"evidence": {"rollback_rate": float("nan")}}
    assert guard.inspect(candidate).accepted is False
