from __future__ import annotations

import hashlib
from uuid import uuid4

from fdai.core.detection.forecast_history_producer import ForecastHistoryProducer
from fdai.core.operational_evidence.issuance import (
    OperationalEvidenceVerifierEngine,
    VerifierIdentity,
)
from fdai.core.operational_evidence.readback.forecast_history import (
    ForecastContextAggregateReadback,
    ForecastHistorySliceReadback,
    StateTransitionForecastHistorySliceSource,
)
from fdai.shared.providers.forecast_context import ForecastContextEvidence
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceRequest,
    OperationalEvidenceIssuanceStatus,
    OperationalEvidenceLocator,
    OperationalEvidenceLookup,
    OperationalEvidenceRejectionClass,
)
from tests.core.detection.test_forecast_history_producer import (
    MemoryStore,
    Source,
    binding,
    record,
    request,
)
from tests.core.detection.test_forecast_history_producer import (
    history as forecast_history,
)
from tests.core.operational_evidence.support import NOW as VERIFY_AT
from tests.core.operational_evidence.support import MemoryProofStore, anchors, history


async def _produce(kind: str, source: Source, store: MemoryStore) -> str:
    producer = ForecastHistoryProducer(
        binding=binding(kind),
        history=forecast_history(kind),
        source=source,
        store=store,
    )
    receipt = await producer.produce(request(as_of=VERIFY_AT))
    assert receipt.complete
    source_reader = StateTransitionForecastHistorySliceSource(
        store=store, bindings=(forecast_history(kind),)
    )
    evidence = await source_reader.read_slice(
        purpose_id=f"forecast-history-{kind}", request=request(as_of=VERIFY_AT)
    )
    assert evidence is not None
    return evidence.digest


async def _issue(kind: str, digest: str, store: MemoryStore) -> tuple[str, object | None]:
    proofs = MemoryProofStore()
    source_revision = "0" * 64
    source_reader = StateTransitionForecastHistorySliceSource(
        store=store, bindings=(forecast_history(kind),)
    )
    evidence = await source_reader.read_slice(
        purpose_id=f"forecast-history-{kind}", request=request(as_of=VERIFY_AT)
    )
    if evidence is not None:
        source_revision = evidence.source_revision
    engine = OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity("operational-evidence-verifier", "1.0.0"),
        history=lambda: history(),
        anchors=anchors(),
        readbacks=(
            ForecastHistorySliceReadback(
                source=StateTransitionForecastHistorySliceSource(
                    store=store, bindings=(forecast_history(kind),)
                )
            ),
        ),
        writer=proofs,
        clock=lambda: VERIFY_AT,
    )
    response = await engine.issue(
        OperationalEvidenceIssuanceRequest(
            attempt_id=uuid4().hex,
            lookup=OperationalEvidenceLookup(
                evidence_digest="sha256:" + digest,
                scope_digest="sha256:" + request().access_scope_digest,
                purpose_id=f"forecast-history-{kind}",
                source_revision=source_revision,
            ),
            locator=OperationalEvidenceLocator(
                purpose_id=f"forecast-history-{kind}",
                coordinates={
                    "access_scope_digest": request().access_scope_digest,
                    "target_digest": request().target_digest,
                    "horizon_started_at": request(as_of=VERIFY_AT).horizon_started_at.isoformat(),
                    "horizon_ended_at": request(as_of=VERIFY_AT).horizon_ended_at.isoformat(),
                },
            ),
            producer_id="core-control-plane",
            producer_version="1.0.0",
            requested_at=VERIFY_AT,
        ),
        caller_principal="fdai_core",
    )
    rejection = proofs.rejections[-1] if proofs.rejections else None
    return response.status.value, rejection


async def _issue_context(
    evidence: ForecastContextEvidence, store: MemoryStore
) -> tuple[str, object | None]:
    proofs = MemoryProofStore()
    source_reader = StateTransitionForecastHistorySliceSource(
        store=store,
        bindings=tuple(
            forecast_history(kind)
            for kind in ("actions", "changes", "excluded_windows", "resource_lifecycle")
        ),
    )
    engine = OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity("operational-evidence-verifier", "1.0.0"),
        history=lambda: history(),
        anchors=anchors(),
        readbacks=(ForecastContextAggregateReadback(source=source_reader),),
        writer=proofs,
        clock=lambda: VERIFY_AT,
    )
    response = await engine.issue(
        OperationalEvidenceIssuanceRequest(
            attempt_id=uuid4().hex,
            lookup=OperationalEvidenceLookup(
                evidence_digest="sha256:" + evidence.digest,
                scope_digest="sha256:" + evidence.access_scope_digest,
                purpose_id="forecast-context",
                source_revision=evidence.source_revision,
            ),
            locator=OperationalEvidenceLocator(
                purpose_id="forecast-context",
                coordinates={
                    "access_scope_digest": evidence.access_scope_digest,
                    "target_digest": evidence.target_digest,
                    "horizon_started_at": evidence.horizon_started_at.isoformat(),
                    "horizon_ended_at": evidence.horizon_ended_at.isoformat(),
                },
            ),
            producer_id="core-control-plane",
            producer_version="1.0.0",
            requested_at=VERIFY_AT,
        ),
        caller_principal="fdai_core",
    )
    rejection = proofs.rejections[-1] if proofs.rejections else None
    return response.status.value, rejection


async def test_changes_forecast_history_issues_from_state_transition_source_rows() -> None:
    store = MemoryStore()
    digest = await _produce("changes", Source("changes", (record("c", "full:upsert", 5),)), store)

    status, rejection = await _issue("changes", digest, store)

    assert status == OperationalEvidenceIssuanceStatus.ISSUED.value
    assert rejection is None


async def test_resource_lifecycle_forecast_history_issues_from_incarnation_boundaries() -> None:
    store = MemoryStore()
    digest = await _produce(
        "resource_lifecycle",
        Source("resource_lifecycle", (record("gone", "deleted", 20),), initial="present"),
        store,
    )

    status, rejection = await _issue("resource_lifecycle", digest, store)

    assert status == OperationalEvidenceIssuanceStatus.ISSUED.value
    assert rejection is None


async def test_excluded_windows_forecast_history_issues_from_change_window_history() -> None:
    store = MemoryStore()
    digest = await _produce(
        "excluded_windows",
        Source("excluded_windows", (record("open", "open", 10),), initial="closed"),
        store,
    )

    status, rejection = await _issue("excluded_windows", digest, store)

    assert status == OperationalEvidenceIssuanceStatus.ISSUED.value
    assert rejection is None


async def test_forecast_context_issues_from_all_four_source_slices() -> None:
    store = MemoryStore()
    for kind, source in {
        "actions": Source("actions", (record("run", "succeeded", 10),)),
        "changes": Source("changes", (record("change", "full:upsert", 5),)),
        "excluded_windows": Source("excluded_windows", initial="closed"),
        "resource_lifecycle": Source("resource_lifecycle", initial="present"),
    }.items():
        await _produce(kind, source, store)
    reader = StateTransitionForecastHistorySliceSource(
        store=store,
        bindings=tuple(
            forecast_history(kind)
            for kind in ("actions", "changes", "excluded_windows", "resource_lifecycle")
        ),
    )
    context = request(as_of=VERIFY_AT)
    slices = [
        await reader.read_slice(purpose_id=f"forecast-history-{kind}", request=context)
        for kind in ("actions", "changes", "excluded_windows", "resource_lifecycle")
    ]
    assert all(item is not None for item in slices)
    typed = [item for item in slices if item is not None]
    aggregate = ForecastContextEvidence(
        access_scope_digest=typed[0].access_scope_digest,
        target_digest=typed[0].target_digest,
        horizon_started_at=typed[0].horizon_started_at,
        horizon_ended_at=typed[0].horizon_ended_at,
        recorded_at=max(item.recorded_at for item in typed),
        valid_until=min(item.valid_until for item in typed),
        complete=all(item.complete for item in typed),
        source_revision=hashlib.sha256("".join(item.digest for item in typed).encode()).hexdigest(),
        evidence_refs=tuple(sorted({ref for item in typed for ref in item.evidence_refs})),
        intervention_refs=tuple(sorted({ref for item in typed for ref in item.intervention_refs})),
        resource_deleted=any(item.resource_deleted for item in typed),
        excluded_window=any(item.excluded_window for item in typed),
    )

    status, rejection = await _issue_context(aggregate, store)

    assert status == OperationalEvidenceIssuanceStatus.ISSUED.value
    assert rejection is None


async def test_forecast_history_rejects_incomplete_source_coverage() -> None:
    store = MemoryStore()
    producer = ForecastHistoryProducer(
        binding=binding("changes"),
        history=forecast_history("changes"),
        source=Source("changes", limitation="start_checkpoint_unverified"),
        store=store,
    )
    receipt = await producer.produce(request(as_of=VERIFY_AT))
    assert not receipt.complete

    status, rejection = await _issue("changes", "0" * 64, store)

    assert status == OperationalEvidenceIssuanceStatus.REJECTED.value
    assert rejection is not None
    assert rejection.rejection_class is OperationalEvidenceRejectionClass.PARTIAL


async def test_forecast_history_rejects_replay_substituted_digest() -> None:
    store = MemoryStore()
    await _produce("changes", Source("changes", (record("c", "full:upsert", 5),)), store)

    status, rejection = await _issue("changes", "1" * 64, store)

    assert status == OperationalEvidenceIssuanceStatus.REJECTED.value
    assert rejection is not None
    assert rejection.rejection_class is OperationalEvidenceRejectionClass.REPLAY_SUBSTITUTED


async def test_bound_action_history_without_coverage_rejects_partial() -> None:
    store = MemoryStore()
    await _produce("changes", Source("changes", (record("c", "full:upsert", 5),)), store)

    status, rejection = await _issue("actions", "0" * 64, store)

    assert status == OperationalEvidenceIssuanceStatus.REJECTED.value
    assert rejection is not None
    assert rejection.rejection_class is OperationalEvidenceRejectionClass.PARTIAL
