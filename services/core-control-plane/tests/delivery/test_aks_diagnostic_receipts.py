"""Focused application and persistence tests for AKS diagnostic receipts."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fdai.core.ontology_platform.aks_diagnostic_receipt_service import (
    AksDiagnosticReceiptService,
)
from fdai.core.ontology_platform.kubernetes_diagnostic_assessment import (
    AksDiagnosticContext,
)
from fdai.delivery.aks_diagnostic_receipts import (
    AKS_DIAGNOSTIC_RECEIPT_PREFIX,
    AksDiagnosticReceiptCollisionError,
    InventoryPromotionAksDiagnosticObserver,
    StateStoreAksDiagnosticReceiptWriter,
)
from fdai.delivery.inventory_sync_models import (
    InventoryProjectionSourceState,
    InventoryProjectionSourceStatus,
    PromotedInventoryObservation,
)
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.state_store import StateStore
from fdai_service_contracts.ontology_query import content_digest

_CUTOFF = datetime(2026, 9, 10, 0, 5, tzinfo=UTC)
_RELEASE = f"sha256:{'a' * 64}"
_SCOPE = f"sha256:{'b' * 64}"


class _AtomicStateStore:
    def __init__(self) -> None:
        self.records: dict[str, Mapping[str, Any]] = {}
        self.audit_entries: list[Mapping[str, Any]] = []

    async def write_state_with_audit_if_absent(
        self,
        key: str,
        value: Mapping[str, Any],
        audit_entry: Mapping[str, Any],
    ) -> bool:
        if key in self.records:
            return False
        self.records[key] = value
        self.audit_entries.append(audit_entry)
        return True

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        return self.records.get(key)


def _target(**props: object) -> ResourceRecord:
    return ResourceRecord(
        resource_id="cluster/kubernetes/kubernetes.pod/default/api",
        type="kubernetes.pod",
        props={
            "cluster_ref": "cluster",
            "uid": "uid-api",
            "resource_version": "20",
            "container_waiting_reasons": ("ImagePullBackOff",),
            "provider_message": "must never be persisted",
            **props,
        },
    )


def _context() -> AksDiagnosticContext:
    return AksDiagnosticContext(
        target=_target(),
        related=(),
        event_reasons=(),
        metrics=(),
        api_reachable=None,
        azure_availability=None,
        cutoff=_CUTOFF,
        source_cutoffs={"inventory_snapshot": _CUTOFF},
        source_revisions={"inventory_snapshot": f"sha256:{'c' * 64}"},
        evidence_refs=(f"inventory-generation:sha256:{'d' * 64}",),
        evidence_complete=False,
        ontology_release=_RELEASE,
        principal_class="system",
        audit_correlation_id=f"sha256:{'e' * 64}",
        evidence_gaps=("kubernetes_metric_evidence_unavailable",),
    )


async def test_application_service_atomically_persists_an_idempotent_typed_receipt() -> None:
    state = _AtomicStateStore()
    service = AksDiagnosticReceiptService(
        StateStoreAksDiagnosticReceiptWriter(cast(StateStore, state))
    )

    first = await service.assess_and_persist(_context())
    second = await service.assess_and_persist(_context())

    assert first == second
    assert len(state.records) == 1
    assert len(state.audit_entries) == 1
    key, record = next(iter(state.records.items()))
    assert key.startswith(AKS_DIAGNOSTIC_RECEIPT_PREFIX)
    assert len(key) < 256
    assert record["record_digest"].startswith("sha256:")
    receipt = cast(dict[str, object], record["receipt"])
    assert str(receipt["cutoff"]).endswith("Z")
    expected_key = (
        f"{AKS_DIAGNOSTIC_RECEIPT_PREFIX}"
        f"{hashlib.sha256(first.target_resource_id.encode()).hexdigest()}:"
        f"20260910T000500000000Z:{content_digest(receipt)[7:]}"
    )
    assert key == expected_key
    assert "must never be persisted" not in str(record)
    assert first.cause_claim_supported is False
    assert first.execution_authority is False


async def test_receipt_writer_rejects_a_deterministic_identity_collision() -> None:
    state = _AtomicStateStore()
    service = AksDiagnosticReceiptService(
        StateStoreAksDiagnosticReceiptWriter(cast(StateStore, state))
    )
    await service.assess_and_persist(_context())
    key = next(iter(state.records))
    state.records[key] = {"record_type": "different"}

    with pytest.raises(AksDiagnosticReceiptCollisionError):
        await service.assess_and_persist(_context())


async def test_receipt_identity_includes_complete_assessment_content() -> None:
    state = _AtomicStateStore()
    service = AksDiagnosticReceiptService(
        StateStoreAksDiagnosticReceiptWriter(cast(StateStore, state))
    )
    first = await service.assess_and_persist(_context())
    second = await service.assess_and_persist(
        replace(
            _context(),
            target=_target(
                container_waiting_reasons=(),
                diagnostic_conditions=({"type": "PodScheduled", "status": "False"},),
            ),
        )
    )

    assert first.status != second.status
    assert len(state.records) == 2
    assert len(state.audit_entries) == 2


async def test_inventory_promotion_observer_records_source_identity_and_explicit_gaps() -> None:
    state = _AtomicStateStore()
    observer = InventoryPromotionAksDiagnosticObserver(
        service=AksDiagnosticReceiptService(
            StateStoreAksDiagnosticReceiptWriter(cast(StateStore, state))
        ),
        ontology_release=_RELEASE,
        scope_by_cluster_ref={"cluster": _SCOPE},
    )

    count = await observer.observe(
        PromotedInventoryObservation(
            generation="snapshot-1",
            resources=(_target(),),
            links=(),
            complete=True,
            recorded_at=_CUTOFF,
            source_states=(
                InventoryProjectionSourceState(
                    source="kubernetes_runtime_inventory",
                    status=InventoryProjectionSourceStatus.AVAILABLE,
                    observed_at=_CUTOFF,
                    reason=None,
                    scope_digest=_SCOPE,
                ),
            ),
        )
    )

    assert count == 1
    receipt = next(iter(state.records.values()))["receipt"]
    assert isinstance(receipt, dict)
    assert receipt["target_uid"] == "uid-api"
    assert receipt["target_resource_version"] == "20"
    assert receipt["source_revisions"]["kubernetes_runtime_inventory"] == _SCOPE
    assert receipt["evidence_gaps"] == [
        "kubernetes_lifecycle_evidence_unavailable",
        "kubernetes_metric_evidence_unavailable",
        "azure_control_plane_evidence_unavailable",
        "kubernetes_log_evidence_unavailable",
        "required_evidence_incomplete",
    ]
    assert receipt["complete"] is False
