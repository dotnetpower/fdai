"""F06.2 governance qualification: source holds, frozen cohort, record, ledger reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.governance_qualification import (
    CohortCase,
    GroundTruth,
    HoldReason,
    QualificationBinding,
    Readiness,
    SourceObservation,
    SourceState,
    Verdict,
    build_qualification_record,
    freeze_cohort,
    measure_cohort,
    reconcile_ledger_digests,
    reconcile_sources,
)

CUTOFF = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
MAX_AGE = timedelta(hours=1)
DIGEST = "sha256:" + "a" * 64


def _obs(
    source_id: str = "drift",
    state: SourceState = SourceState.AVAILABLE,
    age: timedelta = timedelta(minutes=5),
    digest: str = DIGEST,
) -> SourceObservation:
    return SourceObservation(
        source_id=source_id,
        scope_id="scope-1",
        identity_ref="identity-1",
        state=state,
        observed_at=CUTOFF - age,
        evidence_digest=digest,
    )


def _binding(
    cutoff: datetime = CUTOFF, rule_digest: str = "sha256:" + "b" * 64
) -> QualificationBinding:
    return QualificationBinding(
        installation_id="inst-1",
        management_scope_id="scope-1",
        environment_class="development",
        rule_generation_digest=rule_digest,
        ontology_release_digest="sha256:" + "c" * 64,
        provider_revisions={"drift": "r1", "control-gap": "r2"},
        evidence_cutoff=cutoff,
    )


def _sources(*observations: SourceObservation):
    return reconcile_sources(
        observations,
        required_source_ids=["drift", "control-gap"],
        evidence_cutoff=CUTOFF,
        max_age=MAX_AGE,
    )


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (SourceState.UNAVAILABLE, HoldReason.UNAVAILABLE),
        (SourceState.STALE, HoldReason.STALE),
        (SourceState.INCOMPLETE, HoldReason.INCOMPLETE),
        (SourceState.REVOKED, HoldReason.REVOKED),
        (SourceState.CONFLICTING, HoldReason.CONFLICTING),
    ],
)
def test_every_non_available_state_is_an_explicit_hold(state, reason) -> None:
    result = _sources(_obs("drift", state), _obs("control-gap"))

    assert [(h.source_id, h.reason) for h in result.holds] == [("drift", reason)]
    assert [item.source_id for item in result.admitted] == ["control-gap"]
    assert not result.complete


def test_missing_required_source_is_a_hold_not_a_pass() -> None:
    result = _sources(_obs("drift"))

    assert [(h.source_id, h.reason) for h in result.holds] == [
        ("control-gap", HoldReason.MISSING_REQUIRED)
    ]


def test_old_observation_is_stale_and_future_observation_is_rejected() -> None:
    old = _obs("drift", age=MAX_AGE + timedelta(seconds=1))
    future = _obs("control-gap", age=-timedelta(minutes=1))

    result = _sources(old, future)

    assert {(h.source_id, h.reason) for h in result.holds} == {
        ("drift", HoldReason.STALE),
        ("control-gap", HoldReason.OBSERVED_AFTER_CUTOFF),
    }


def test_conflicting_duplicate_observations_are_held() -> None:
    result = _sources(
        _obs("drift"), _obs("drift", digest="sha256:" + "d" * 64), _obs("control-gap")
    )

    assert [(h.source_id, h.reason) for h in result.holds] == [
        ("drift", HoldReason.DUPLICATE_CONFLICT)
    ]


def test_identical_duplicates_collapse_and_a_complete_set_has_no_holds() -> None:
    result = _sources(_obs("drift"), _obs("drift"), _obs("control-gap"))

    assert result.complete
    assert [item.source_id for item in result.admitted] == ["control-gap", "drift"]


def test_reconciliation_digest_is_order_independent_and_changes_with_content() -> None:
    first = _sources(_obs("drift"), _obs("control-gap"))
    second = _sources(_obs("control-gap"), _obs("drift"))
    third = _sources(_obs("drift"), _obs("control-gap", digest="sha256:" + "e" * 64))

    assert first.digest == second.digest
    assert first.digest != third.digest


def test_naive_times_and_bad_inputs_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        SourceObservation("s", "sc", "id", SourceState.AVAILABLE, datetime(2026, 1, 1), DIGEST)
    with pytest.raises(ValueError, match="positive"):
        reconcile_sources(
            [], required_source_ids=["s"], evidence_cutoff=CUTOFF, max_age=timedelta(0)
        )
    with pytest.raises(ValueError, match="at least one required"):
        reconcile_sources([], required_source_ids=[], evidence_cutoff=CUTOFF, max_age=MAX_AGE)


def _case(index: int, truth: GroundTruth, verdict: Verdict, group: str | None = None) -> CohortCase:
    return CohortCase(f"c{index:03d}", group or f"g{index:03d}", truth, verdict)


def _cohort():
    cases = (
        [_case(i, GroundTruth.VIOLATION, Verdict.FLAGGED) for i in range(8)]
        + [_case(10, GroundTruth.VIOLATION, Verdict.NOT_FLAGGED)]
        + [_case(11, GroundTruth.VIOLATION, Verdict.HELD)]
        + [_case(20 + i, GroundTruth.COMPLIANT, Verdict.NOT_FLAGGED) for i in range(17)]
        + [_case(40, GroundTruth.COMPLIANT, Verdict.FLAGGED)]
        + [_case(41, GroundTruth.COMPLIANT, Verdict.HELD)]
    )
    return freeze_cohort(cases)


def test_measurement_counts_rates_and_never_counts_a_hold_as_correct() -> None:
    cohort = _cohort()

    m = measure_cohort(cohort, expected_digest=cohort.digest)

    assert (m.true_positive, m.false_negative, m.false_positive, m.true_negative) == (8, 1, 1, 17)
    assert (m.held_violation, m.held_compliant, m.total) == (1, 1, 29)
    assert m.false_negative_rate is not None and m.false_negative_rate.denominator == 9
    assert m.false_positive_rate is not None and m.false_positive_rate.denominator == 18
    assert m.coverage is not None and m.coverage.numerator == 27
    worst = m.false_negative_rate_worst_case
    assert worst is not None and worst.numerator == 2 and worst.denominator == 10
    assert worst.value > m.false_negative_rate.value
    fpr = m.false_positive_rate
    assert 0.0 <= fpr.lower <= fpr.value <= fpr.upper <= 1.0


def test_zero_denominators_are_absent_not_zero() -> None:
    cohort = freeze_cohort([_case(1, GroundTruth.COMPLIANT, Verdict.NOT_FLAGGED)])

    m = measure_cohort(cohort, expected_digest=cohort.digest)

    assert m.false_negative_rate is None
    assert m.false_negative_rate_worst_case is None
    assert m.false_positive_rate is not None


def test_independent_group_count_uses_the_declared_unit() -> None:
    cohort = freeze_cohort(
        [_case(i, GroundTruth.VIOLATION, Verdict.FLAGGED, group="incident-1") for i in range(5)]
        + [_case(9, GroundTruth.COMPLIANT, Verdict.NOT_FLAGGED, group="incident-2")]
    )

    assert measure_cohort(cohort, expected_digest=cohort.digest).independent_groups == 2


def test_a_changed_cohort_fails_closed_against_the_frozen_digest() -> None:
    frozen = _cohort()
    tampered = type(frozen)(frozen.cases[:-1], frozen.digest)

    with pytest.raises(ValueError, match="frozen denominator"):
        measure_cohort(tampered, expected_digest=frozen.digest)
    with pytest.raises(ValueError, match="frozen denominator"):
        measure_cohort(frozen, expected_digest="sha256:" + "0" * 64)


def test_empty_and_duplicate_cohorts_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least one"):
        freeze_cohort([])
    with pytest.raises(ValueError, match="unique"):
        freeze_cohort([_case(1, GroundTruth.VIOLATION, Verdict.FLAGGED)] * 2)


def _clean_cohort():
    return freeze_cohort(
        [_case(i, GroundTruth.VIOLATION, Verdict.FLAGGED) for i in range(5)]
        + [_case(10 + i, GroundTruth.COMPLIANT, Verdict.NOT_FLAGGED) for i in range(5)]
    )


def test_complete_inputs_produce_a_review_only_ready_record() -> None:
    cohort = _clean_cohort()
    measurement = measure_cohort(cohort, expected_digest=cohort.digest)

    record = build_qualification_record(
        _binding(), _sources(_obs("drift"), _obs("control-gap")), measurement
    )

    assert record.readiness is Readiness.READY_FOR_REVIEW
    assert record.blocking_reasons == ()
    assert record.authority == "none"
    assert record.record_digest.startswith("sha256:")


def test_every_hold_and_missing_measurement_blocks_by_name() -> None:
    record = build_qualification_record(
        _binding(), _sources(_obs("drift", SourceState.REVOKED)), None
    )

    assert record.readiness is Readiness.BLOCKED
    assert record.blocking_reasons == (
        "cohort_not_measured",
        "source_hold:control-gap:missing_required",
        "source_hold:drift:revoked",
    )


def test_cohort_holds_and_cutoff_mismatch_block() -> None:
    cohort = _cohort()
    measurement = measure_cohort(cohort, expected_digest=cohort.digest)

    record = build_qualification_record(
        _binding(CUTOFF + timedelta(hours=1)),
        _sources(_obs("drift"), _obs("control-gap")),
        measurement,
    )

    assert record.readiness is Readiness.BLOCKED
    assert "cohort_has_holds" in record.blocking_reasons
    assert "source_cutoff_differs_from_binding" in record.blocking_reasons


def test_record_digest_binds_the_exact_revisions() -> None:
    cohort = _clean_cohort()
    measurement = measure_cohort(cohort, expected_digest=cohort.digest)
    sources = _sources(_obs("drift"), _obs("control-gap"))
    first = build_qualification_record(_binding(), sources, measurement)
    changed = build_qualification_record(
        _binding(rule_digest="sha256:" + "f" * 64), sources, measurement
    )
    repeated = build_qualification_record(_binding(), sources, measurement)

    assert changed.record_digest != first.record_digest
    assert repeated.record_digest == first.record_digest


def test_binding_rejects_unpinned_or_malformed_revisions() -> None:
    ok = "sha256:" + "c" * 64
    with pytest.raises(ValueError, match="sha256"):
        QualificationBinding("i", "s", "development", "bad", ok, {"p": "r"}, CUTOFF)
    with pytest.raises(ValueError, match="pin every provider"):
        QualificationBinding("i", "s", "development", ok, ok, {}, CUTOFF)


def test_ledger_reconciliation_reports_missing_digests() -> None:
    cohort = _clean_cohort()
    measurement = measure_cohort(cohort, expected_digest=cohort.digest)
    record = build_qualification_record(
        _binding(), _sources(_obs("drift"), _obs("control-gap")), measurement
    )

    assert (
        reconcile_ledger_digests(
            record, {record.record_digest, record.sources_digest, measurement.digest}
        )
        == ()
    )
    assert reconcile_ledger_digests(record, {record.record_digest}) == tuple(
        sorted({record.sources_digest, measurement.digest})
    )
