"""Focused bounded live evidence write-through tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.delivery.inventory_live_evidence import InventoryLiveEvidenceWriter
from fdai.delivery.persistence.postgres_inventory_delta import (
    InventoryDeltaApplyOutcome,
    InventoryDeltaApplyResult,
    PostgresInventoryDeltaProjector,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.shared.providers.read_investigation import (
    EvidenceFreshness,
    EvidenceStatus,
    ReadEvidenceEnvelope,
    ReadEvidenceRecord,
    ResolvedResource,
)

_NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)
_RELEASE = "sha256:" + "a" * 64


class _Ingress:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def __call__(self, payload: dict[str, Any]) -> InventoryDeltaApplyResult:
        self.payloads.append(payload)
        return InventoryDeltaApplyResult(
            resources=1,
            links=0,
            outcome=InventoryDeltaApplyOutcome.APPLIED,
        )


def _resource() -> ResolvedResource:
    return ResolvedResource(
        resource_ref="resource:vm-1",
        scope_ref="scope:example",
        name="vm-1",
        resource_type="compute.vm",
    )


def _evidence(**changes: object) -> ReadEvidenceEnvelope:
    values: dict[str, object] = {
        "status": EvidenceStatus.MATCHED,
        "authority": "provider-read",
        "resource_ref": "resource:vm-1",
        "observed_at": _NOW,
        "freshness": EvidenceFreshness.LIVE,
        "truncated": False,
        "records": (ReadEvidenceRecord(occurred_at=_NOW, status="observed", state="running"),),
        "evidence_refs": ("provider-read:receipt-1",),
    }
    values.update(changes)
    return ReadEvidenceEnvelope(**values)  # type: ignore[arg-type]


async def test_verified_live_evidence_uses_partial_overlay_upsert() -> None:
    ingress = _Ingress()
    writer = InventoryLiveEvidenceWriter(ingress=ingress)

    receipt = await writer.publish(
        resource=_resource(),
        evidence=_evidence(),
        ontology_release_digest=_RELEASE,
    )

    change = ingress.payloads[0]["inventory_change"]
    assert receipt.published is True
    assert receipt.projector_outcome is InventoryDeltaApplyOutcome.APPLIED
    assert receipt.observation_authority is False
    assert receipt.mutation_authority is False
    assert receipt.execution_authority is False
    assert change["kind"] == "upsert"
    assert change["properties_complete"] is False
    assert change["links_complete"] is False
    assert change["links"] == []


async def test_stale_or_truncated_evidence_never_reaches_ingress() -> None:
    ingress = _Ingress()
    writer = InventoryLiveEvidenceWriter(ingress=ingress)

    stale = await writer.publish(
        resource=_resource(),
        evidence=_evidence(freshness=EvidenceFreshness.STALE),
        ontology_release_digest=_RELEASE,
    )

    assert stale.published is False
    assert stale.reason_code == "live_evidence_unverified"
    assert ingress.payloads == []


async def test_duplicate_live_receipt_reuses_observation_identity() -> None:
    ingress = _Ingress()
    writer = InventoryLiveEvidenceWriter(ingress=ingress)

    first = await writer.publish(
        resource=_resource(),
        evidence=_evidence(),
        ontology_release_digest=_RELEASE,
    )
    second = await writer.publish(
        resource=_resource(),
        evidence=_evidence(),
        ontology_release_digest=_RELEASE,
    )

    assert second.event_id == first.event_id
    assert second.idempotency_key == first.idempotency_key
    assert ingress.payloads[1] == ingress.payloads[0]


@pytest.mark.parametrize(
    "change",
    [
        {
            "kind": "delete",
            "observation_kind": "partial",
            "properties_complete": False,
            "resource": {
                "resource_id": "resource:vm-1",
                "type": "compute.vm",
                "props": {},
                "last_seen": _NOW.isoformat(),
            },
            "links": [],
        },
        {
            "kind": "upsert",
            "observation_kind": "partial",
            "properties_complete": False,
            "resource": {
                "resource_id": "resource:vm-1",
                "type": "compute.vm",
                "props": {},
                "last_seen": _NOW.isoformat(),
            },
            "links_complete": True,
            "links": [],
        },
    ],
)
async def test_partial_properties_cannot_delete_or_replace_relationships(
    change: dict[str, Any],
) -> None:
    projector = PostgresInventoryDeltaProjector(
        config=PostgresInventorySnapshotStoreConfig(dsn="postgresql://example.invalid/fdai"),
        clock=lambda: _NOW,
    )

    with pytest.raises(ValueError, match="partial inventory properties"):
        await projector(
            {
                "event_id": "event-invalid-partial",
                "idempotency_key": "invalid-partial",
                "inventory_change": change,
            }
        )
