"""Independent effect observation receipt, ledger, and hold semantics.

These tests exist to prove one property above all others: no observation,
however it is shaped, can turn into permission to act. Verified closes an
effect, failed may only *request* a separately governed recovery, and every
other outcome is a hold.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.executor.effect_observation import (
    UNKNOWN_OUTCOMES,
    IndependentEffectDisposition,
    IndependentEffectObservationBinding,
    IndependentEffectObservationReceipt,
    IndependentEffectOutcome,
    ObservationCompleteness,
    ObservationContainment,
    ObservationFinality,
    ObservationQuality,
    disposition_for,
    quality_downgrade,
)
from fdai.core.executor.effect_observation_codec import (
    observation_receipt_from_mapping,
    observation_receipt_to_mapping,
)
from fdai.core.executor.effect_observation_ledger import (
    GovernedRecoveryRequest,
    IndependentEffectConflictError,
    IndependentEffectLedger,
    IndependentEffectLedgerError,
    project_state,
)
from fdai.core.executor.execution_provenance import (
    SafeguardExecutionOrigin,
    SafeguardExecutionVenue,
)
from fdai.core.executor.safeguard_dispatch_support import payload_digest
from fdai.core.executor.testing_effect_observation import (
    InMemoryIndependentEffectObservationStore,
)

_NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
_OBSERVER = "fdai.observer.independent"
_EXECUTOR = "fdai.executor.core"
_SOURCE = "azure.arm.instance-view"


def _digest(seed: str) -> str:
    return "sha256:" + (seed * 64)[:64]


def _binding(
    *,
    venue: SafeguardExecutionVenue = SafeguardExecutionVenue.CORE,
    origin: SafeguardExecutionOrigin = SafeguardExecutionOrigin.CORE,
    path: str = "direct_api",
) -> IndependentEffectObservationBinding:
    return IndependentEffectObservationBinding.create(
        action_id="00000000-0000-0000-0000-000000000001",
        action_payload_digest=_digest("a"),
        target_digest=_digest("b"),
        source_revision="commit:" + "c" * 40,
        execution_path=path,
        execution_origin=origin,
        execution_venue=venue,
        safeguard_bundle_digest=_digest("d"),
        evidence_identity_digest=_digest("e"),
        evidence_record_digest=_digest("f"),
        evidence_record_revision=1,
        executor_receipt_digest=_digest("1"),
    )


def _quality(**overrides: Any) -> ObservationQuality:
    values: dict[str, Any] = {
        "schema_version": "1.0.0",
        "evidence_window_start": _NOW - timedelta(minutes=5),
        "evidence_window_end": _NOW,
        "source_recorded_at": _NOW - timedelta(minutes=1),
        "max_source_age_seconds": 900.0,
        "finality": ObservationFinality.FINAL,
        "completeness": ObservationCompleteness.COMPLETE,
        "containment": ObservationContainment.WITHIN_DECLARED_TARGET,
        "conflicting_source_count": 0,
        "synthetic": False,
    }
    values.update(overrides)
    return ObservationQuality(**values)


def _receipt(
    *,
    outcome: IndependentEffectOutcome = IndependentEffectOutcome.VERIFIED,
    sequence: int = 1,
    prior: str | None = None,
    quality: ObservationQuality | None = None,
    binding: IndependentEffectObservationBinding | None = None,
    observer: str = _OBSERVER,
    executor: str = _EXECUTOR,
    source: str = _SOURCE,
) -> IndependentEffectObservationReceipt:
    return IndependentEffectObservationReceipt.create(
        observation_id=f"observation-{sequence}",
        binding=binding or _binding(),
        quality=quality or _quality(),
        outcome=outcome,
        reason="focused test observation",
        observer_instance_id=observer,
        executor_instance_id=executor,
        source_instance_id=source,
        observed_at=_NOW,
        completed_at=_NOW + timedelta(seconds=1),
        sequence=sequence,
        prior_receipt_digest=prior,
    )


# -- outcome / disposition mapping -------------------------------------------


@pytest.mark.parametrize("outcome", sorted(UNKNOWN_OUTCOMES))
def test_every_inconclusive_outcome_is_an_unknown_hold(
    outcome: IndependentEffectOutcome,
) -> None:
    assert disposition_for(outcome) is IndependentEffectDisposition.UNKNOWN_HOLD


def test_only_a_verified_outcome_closes_the_effect() -> None:
    assert (
        disposition_for(IndependentEffectOutcome.VERIFIED)
        is IndependentEffectDisposition.EFFECT_VERIFIED
    )
    assert (
        disposition_for(IndependentEffectOutcome.FAILED)
        is IndependentEffectDisposition.RECOVERY_REQUIRED
    )


def test_a_receipt_grants_no_authority_of_any_kind() -> None:
    receipt = _receipt()

    assert receipt.execution_authority is False
    assert receipt.sink_commit_authority is False
    assert receipt.lock_release_authority is False
    assert receipt.promotion_authority is False


def test_a_disposition_may_not_contradict_its_outcome() -> None:
    receipt = _receipt()

    with pytest.raises(ValueError, match="disposition contradicts its outcome"):
        replace(receipt, disposition=IndependentEffectDisposition.UNKNOWN_HOLD)


# -- quality downgrades -------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "expected"),
    (
        ({"synthetic": True}, IndependentEffectOutcome.UNAVAILABLE),
        ({"conflicting_source_count": 2}, IndependentEffectOutcome.CONFLICTING),
        ({"max_source_age_seconds": 1.0}, IndependentEffectOutcome.STALE),
        (
            {"finality": ObservationFinality.PROVISIONAL},
            IndependentEffectOutcome.STALE,
        ),
        (
            {"completeness": ObservationCompleteness.PARTIAL},
            IndependentEffectOutcome.CENSORED,
        ),
        (
            {"containment": ObservationContainment.EXCEEDS_DECLARED_TARGET},
            IndependentEffectOutcome.CONFLICTING,
        ),
        (
            {"containment": ObservationContainment.UNKNOWN},
            IndependentEffectOutcome.CONFLICTING,
        ),
    ),
)
def test_weak_evidence_cannot_report_a_verified_effect(
    overrides: dict[str, Any],
    expected: IndependentEffectOutcome,
) -> None:
    quality = _quality(**overrides)

    assert quality_downgrade(quality, observed_at=_NOW) is expected

    receipt = _receipt(outcome=IndependentEffectOutcome.VERIFIED, quality=quality)

    assert receipt.outcome is expected
    assert receipt.effect_verified is False
    assert receipt.disposition is IndependentEffectDisposition.UNKNOWN_HOLD


def test_weak_evidence_cannot_report_a_failed_effect_either() -> None:
    receipt = _receipt(
        outcome=IndependentEffectOutcome.FAILED,
        quality=_quality(completeness=ObservationCompleteness.PARTIAL),
    )

    assert receipt.outcome is IndependentEffectOutcome.CENSORED
    assert receipt.disposition is IndependentEffectDisposition.UNKNOWN_HOLD


def test_a_verified_receipt_may_not_be_forged_from_weak_quality() -> None:
    strong = _receipt()

    with pytest.raises(ValueError, match="complete, final, exact evidence"):
        replace(strong, quality=_quality(synthetic=True))


def test_an_evidence_window_must_stay_bounded() -> None:
    with pytest.raises(ValueError, match="window MUST stay bounded"):
        _quality(
            evidence_window_start=_NOW - timedelta(days=2),
            source_recorded_at=_NOW - timedelta(days=1),
        )


def test_a_source_reading_must_sit_inside_its_own_window() -> None:
    with pytest.raises(ValueError, match="outside its window"):
        _quality(source_recorded_at=_NOW + timedelta(minutes=1))


# -- identity independence ----------------------------------------------------


@pytest.mark.parametrize(
    ("observer", "executor", "source"),
    (
        (_OBSERVER, _OBSERVER, _SOURCE),
        (_OBSERVER, _EXECUTOR, _OBSERVER),
        (_OBSERVER, _EXECUTOR, _EXECUTOR),
        (_OBSERVER, _EXECUTOR, _OBSERVER.upper()),
    ),
)
def test_observer_executor_and_source_identities_must_be_distinct(
    observer: str,
    executor: str,
    source: str,
) -> None:
    with pytest.raises(ValueError, match="identities MUST be distinct"):
        _receipt(observer=observer, executor=executor, source=source)


# -- digest integrity ---------------------------------------------------------


def test_tampering_with_a_retained_receipt_breaks_its_digest() -> None:
    receipt = _receipt()

    with pytest.raises(ValueError, match="receipt digest mismatched"):
        replace(receipt, reason="a different reason")


def test_tampering_with_a_binding_breaks_its_digest() -> None:
    binding = _binding()

    with pytest.raises(ValueError, match="binding digest mismatched"):
        replace(binding, execution_venue=SafeguardExecutionVenue.ISOLATED_EXECUTOR.value)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("execution_origin", "not-an-origin"),
        ("execution_venue", "not-a-venue"),
    ),
)
def test_unknown_binding_provenance_is_refused(field: str, value: str) -> None:
    binding = _binding()
    values = {name: getattr(binding, name) for name in binding.__dataclass_fields__}
    values.pop("binding_digest")
    values[field] = value
    values["binding_digest"] = payload_digest(
        values,
        "independent-effect-observation-binding",
        digest_field="binding_digest",
    )

    with pytest.raises(ValueError, match="binding provenance is invalid"):
        IndependentEffectObservationBinding(**values)  # type: ignore[arg-type]


def test_a_receipt_survives_a_serialization_round_trip() -> None:
    receipt = _receipt()

    restored = observation_receipt_from_mapping(observation_receipt_to_mapping(receipt))

    assert restored == receipt


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", "2.0.0"),
        ("outcome", "invented"),
        ("effect_verified", "yes"),
        ("execution_authority", True),
        ("sink_commit_authority", True),
        ("lock_release_authority", True),
        ("promotion_authority", True),
        ("observed_at", "2026-09-13T12:00:00"),
        ("sequence", True),
    ),
)
def test_a_malformed_stored_receipt_is_refused(field: str, value: object) -> None:
    mapping = observation_receipt_to_mapping(_receipt())
    mapping[field] = value

    with pytest.raises(ValueError):
        observation_receipt_from_mapping(mapping)


# -- lineage and state projection --------------------------------------------


@pytest.mark.asyncio
async def test_a_verified_observation_closes_the_effect_without_authority() -> None:
    ledger = IndependentEffectLedger(store=InMemoryIndependentEffectObservationStore())

    state = await ledger.record(_receipt())

    assert state.disposition is IndependentEffectDisposition.EFFECT_VERIFIED
    assert state.effect_verified is True
    assert state.permits_new_effect is False
    assert state.recovery_request is None


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", sorted(UNKNOWN_OUTCOMES))
async def test_an_unknown_observation_holds_and_authorizes_nothing(
    outcome: IndependentEffectOutcome,
) -> None:
    ledger = IndependentEffectLedger(store=InMemoryIndependentEffectObservationStore())

    state = await ledger.record(_receipt(outcome=outcome))

    assert state.disposition is IndependentEffectDisposition.UNKNOWN_HOLD
    assert state.effect_verified is False
    assert state.permits_new_effect is False
    assert state.recovery_request is None


@pytest.mark.asyncio
async def test_a_failed_observation_only_requests_a_governed_recovery() -> None:
    ledger = IndependentEffectLedger(store=InMemoryIndependentEffectObservationStore())

    state = await ledger.record(
        _receipt(outcome=IndependentEffectOutcome.FAILED),
        recovery_requested_at=_NOW,
    )

    assert state.disposition is IndependentEffectDisposition.RECOVERY_REQUIRED
    assert state.permits_new_effect is False
    request = state.recovery_request
    assert request is not None
    assert request.requires_seven_safeguards is True
    assert request.requires_current_human_approval is True
    assert request.execution_authority is False
    assert request.promotion_authority is False


def test_only_a_failed_observation_may_request_recovery() -> None:
    with pytest.raises(ValueError, match="failed observation may request recovery"):
        GovernedRecoveryRequest.create(_receipt(), requested_at=_NOW)


@pytest.mark.asyncio
async def test_replaying_the_same_observation_is_idempotent() -> None:
    store = InMemoryIndependentEffectObservationStore()
    ledger = IndependentEffectLedger(store=store)
    receipt = _receipt()

    first = await ledger.record(receipt)
    second = await ledger.record(receipt)

    assert first == second
    assert second.observation_count == 1


@pytest.mark.asyncio
async def test_a_different_observation_may_not_reuse_a_sequence_position() -> None:
    store = InMemoryIndependentEffectObservationStore()
    await store.append(_receipt())

    with pytest.raises(IndependentEffectLedgerError, match="already occupies"):
        await store.append(_receipt(outcome=IndependentEffectOutcome.FAILED))


@pytest.mark.asyncio
async def test_an_out_of_order_observation_is_refused() -> None:
    store = InMemoryIndependentEffectObservationStore()

    with pytest.raises(IndependentEffectLedgerError, match="contiguous"):
        await store.append(_receipt(sequence=2, prior=_digest("9")))


@pytest.mark.asyncio
async def test_a_later_observation_may_not_reopen_a_closed_effect() -> None:
    store = InMemoryIndependentEffectObservationStore()
    ledger = IndependentEffectLedger(store=store)
    verified = _receipt()
    await ledger.record(verified)

    contradiction = _receipt(
        outcome=IndependentEffectOutcome.FAILED,
        sequence=2,
        prior=verified.receipt_digest,
    )

    with pytest.raises(IndependentEffectConflictError, match="contradicts"):
        await ledger.record(contradiction)

    # The contradicting observation is still retained as evidence.
    assert len(await store.read_lineage(verified.binding.evidence_identity_digest)) == 2


@pytest.mark.asyncio
async def test_an_unknown_observation_after_a_verified_one_stays_closed() -> None:
    store = InMemoryIndependentEffectObservationStore()
    ledger = IndependentEffectLedger(store=store)
    verified = _receipt()
    await ledger.record(verified)

    state = await ledger.record(
        _receipt(
            outcome=IndependentEffectOutcome.UNAVAILABLE,
            sequence=2,
            prior=verified.receipt_digest,
        )
    )

    assert state.disposition is IndependentEffectDisposition.EFFECT_VERIFIED


@pytest.mark.asyncio
async def test_an_absent_lineage_is_a_hold_not_a_success() -> None:
    """Absence of evidence never reads as absence of effect."""

    ledger = IndependentEffectLedger(store=InMemoryIndependentEffectObservationStore())

    state = await ledger.state(_digest("e"))

    assert state.outcome is IndependentEffectOutcome.MISSING
    assert state.disposition is IndependentEffectDisposition.UNKNOWN_HOLD
    assert state.effect_verified is False
    assert state.permits_new_effect is False
    assert state.observation_count == 0
    assert state.latest_receipt_digest is None


def test_a_broken_lineage_chain_is_refused() -> None:
    first = _receipt()
    forged = _receipt(sequence=2, prior=_digest("9"))

    with pytest.raises(IndependentEffectLedgerError, match="chain is broken"):
        project_state(
            (first, forged),
            evidence_identity_digest=first.binding.evidence_identity_digest,
        )


def test_a_lineage_may_not_span_two_dispatches() -> None:
    first = _receipt()
    other_binding = IndependentEffectObservationBinding.create(
        action_id="00000000-0000-0000-0000-000000000002",
        action_payload_digest=_digest("a"),
        target_digest=_digest("b"),
        source_revision="commit:" + "c" * 40,
        execution_path="direct_api",
        execution_origin=SafeguardExecutionOrigin.CORE,
        execution_venue=SafeguardExecutionVenue.CORE,
        safeguard_bundle_digest=_digest("d"),
        evidence_identity_digest=_digest("7"),
        evidence_record_digest=_digest("f"),
        evidence_record_revision=1,
        executor_receipt_digest=_digest("1"),
    )
    second = _receipt(sequence=2, prior=first.receipt_digest, binding=other_binding)

    with pytest.raises(IndependentEffectLedgerError, match="spans two dispatches"):
        project_state(
            (first, second),
            evidence_identity_digest=first.binding.evidence_identity_digest,
        )


def test_a_lineage_must_bind_the_requested_dispatch() -> None:
    first = _receipt()

    with pytest.raises(IndependentEffectLedgerError, match="does not bind this dispatch"):
        project_state((first,), evidence_identity_digest=_digest("7"))


@pytest.mark.parametrize(
    ("origin", "venue", "path"),
    (
        (SafeguardExecutionOrigin.WORKFLOW, SafeguardExecutionVenue.CORE, "pr_native"),
        (
            SafeguardExecutionOrigin.CORE,
            SafeguardExecutionVenue.ISOLATED_EXECUTOR,
            "direct_api",
        ),
        (SafeguardExecutionOrigin.CORE, SafeguardExecutionVenue.CORE, "tool_call"),
    ),
)
def test_a_binding_records_the_exact_matrix_cell(
    origin: SafeguardExecutionOrigin,
    venue: SafeguardExecutionVenue,
    path: str,
) -> None:
    binding = _binding(origin=origin, venue=venue, path=path)

    assert binding.execution_origin == origin.value
    assert binding.execution_venue == venue.value
    assert binding.execution_path == path
