"""Runtime-call telemetry binding to the inventory single writer."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.ontology_platform.runtime_call_telemetry import (
    AuthenticatedRuntimeCallContext,
    RuntimeCallTelemetryEnvelope,
    RuntimeCallTelemetryProducer,
)
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.delivery.inventory_topology_history import InventoryTopologyHistoryPublisher
from fdai.delivery.runtime_call_inventory import (
    RuntimeCallInventoryEnricher,
    RuntimeCallTelemetryBatch,
    RuntimeCallTelemetryRecord,
    UnavailableRuntimeCallInventoryEnricher,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.runtime.inventory_ontology import InventoryOntologyProjector
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore, InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 8, 24, 4, 0, tzinfo=UTC)
SCOPE_REF = "scope:operations-review"


def _envelope() -> RuntimeCallTelemetryEnvelope:
    return RuntimeCallTelemetryEnvelope(
        observation_id="runtime-call:one",
        caller_resource_ids=("resource:caller",),
        target_resource_ids=("resource:target",),
        scope_ref=SCOPE_REF,
        observed_at=NOW - timedelta(minutes=2),
        evidence_cutoff=NOW - timedelta(minutes=1),
        recorded_at=NOW,
        freshness_ceiling_seconds=300,
        source_identity="telemetry.runtime-calls",
        source_revision="1.0.0",
        evidence_ref="telemetry:runtime-call:one",
    )


def _context(envelope: RuntimeCallTelemetryEnvelope) -> AuthenticatedRuntimeCallContext:
    return AuthenticatedRuntimeCallContext(
        observation_id=envelope.observation_id,
        observation_digest=envelope.content_digest(),
        source_identity=envelope.source_identity,
        source_credential_lineage="credential-lineage:telemetry",
        verifier_identity="runtime-call-authenticator",
        verifier_credential_lineage="credential-lineage:verifier",
        authentication_ref="sha256:" + "1" * 64,
        verified_at=NOW,
        signature_verified=True,
    )


class _Authenticator:
    async def authenticate(self, *, envelope, claimed_context):  # type: ignore[no-untyped-def]
        del envelope
        return claimed_context


class _Source:
    def __init__(self, batch: RuntimeCallTelemetryBatch) -> None:
        self._batch = batch

    async def collect(
        self,
        observation: PromotedInventoryObservation,
    ) -> RuntimeCallTelemetryBatch:
        del observation
        return self._batch


def _observation() -> PromotedInventoryObservation:
    return PromotedInventoryObservation(
        generation="inventory:generation-one",
        resources=(
            ResourceRecord(resource_id="resource:caller", type="container-app"),
            ResourceRecord(resource_id="resource:target", type="postgres-flexible"),
        ),
        links=(),
        complete=True,
        recorded_at=NOW,
    )


def _enricher(batch: RuntimeCallTelemetryBatch) -> RuntimeCallInventoryEnricher:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    return RuntimeCallInventoryEnricher(
        source=_Source(batch),
        producer=RuntimeCallTelemetryProducer(authenticator=_Authenticator()),
        ontology_release=catalog.build_release(),
        scope_ref=SCOPE_REF,
        endpoint_verifier_identity="inventory.endpoint-verifier",
        endpoint_verifier_revision="1.0.0",
    )


async def test_authenticated_runtime_call_is_added_only_to_single_writer_input() -> None:
    envelope = _envelope()
    enriched = await _enricher(
        RuntimeCallTelemetryBatch(
            records=(RuntimeCallTelemetryRecord(envelope, _context(envelope)),),
            observed_at=NOW + timedelta(seconds=1),
            complete=True,
        )
    ).enrich(_observation())

    assert [(link.from_id, link.link_type, link.to_id) for link in enriched.links] == [
        ("resource:caller", "runtime_calls", "resource:target")
    ]
    assert enriched.links[0].observation_metadata is not None
    assert enriched.links[0].observation_metadata.verified is True
    assert enriched.source_states[0].status.value == "available"
    assert enriched.source_states[0].reason is None


async def test_authentication_failure_adds_no_edge_and_reports_unavailable() -> None:
    envelope = _envelope()
    bad_context = replace(_context(envelope), observation_digest="sha256:" + "2" * 64)
    enriched = await _enricher(
        RuntimeCallTelemetryBatch(
            records=(RuntimeCallTelemetryRecord(envelope, bad_context),),
            observed_at=NOW + timedelta(seconds=1),
            complete=True,
        )
    ).enrich(_observation())

    assert enriched.links == ()
    assert enriched.source_states[0].status.value == "unavailable"
    assert enriched.source_states[0].reason == "telemetry_authentication_failed"


async def test_incomplete_source_adds_no_edge_and_preserves_explicit_reason() -> None:
    enriched = await _enricher(
        RuntimeCallTelemetryBatch(
            records=(),
            observed_at=None,
            complete=False,
            reason="telemetry_scope_unavailable",
        )
    ).enrich(_observation())

    assert enriched.links == ()
    assert enriched.source_states[0].status.value == "unavailable"
    assert enriched.source_states[0].reason == "telemetry_scope_unavailable"


def test_unavailable_source_reason_cannot_carry_raw_details() -> None:
    with pytest.raises(ValueError, match="reason is not allowlisted"):
        RuntimeCallTelemetryBatch(
            records=(),
            observed_at=None,
            complete=False,
            reason="telemetry failed for endpoint secret-value",
        )


async def test_unbound_production_enricher_records_explicit_unavailability() -> None:
    enriched = await UnavailableRuntimeCallInventoryEnricher().enrich(_observation())

    assert enriched.links == ()
    assert enriched.source_states[0].source == "runtime_call_graph"
    assert enriched.source_states[0].status.value == "unavailable"
    assert enriched.source_states[0].reason == "telemetry_source_unavailable"


async def test_runtime_call_flows_through_inventory_current_and_history_projections() -> None:
    envelope = _envelope()
    enriched = await _enricher(
        RuntimeCallTelemetryBatch(
            records=(RuntimeCallTelemetryRecord(envelope, _context(envelope)),),
            observed_at=NOW + timedelta(seconds=1),
            complete=True,
        )
    ).enrich(_observation())
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    status = InMemoryStateStore()
    current = InventoryOntologyProjector(
        store=store,
        status_store=status,
        ontology_release_digest="sha256:" + "a" * 64,
    )

    class _HistoryWriter:
        def __init__(self) -> None:
            self.batches = []

        async def append(self, batch, *, ontology_release_digest, source_receipt_digest):
            self.batches.append((batch, ontology_release_digest, source_receipt_digest))

    writer = _HistoryWriter()
    history = InventoryTopologyHistoryPublisher(
        writer=writer,
        ontology_release_digest="sha256:" + "a" * 64,
    )

    projection = await current.apply(enriched)
    batch = await history.publish(enriched)
    graph = await store.traverse(
        root_ids=("resource:caller",),
        link_types=("runtime_calls",),
        direction="outgoing",
        max_depth=1,
    )

    assert projection.complete is True
    assert projection.link_count == 1
    assert batch is not None
    assert len(writer.batches) == 1
    assert [(link.link_type, link.from_id, link.to_id) for link in graph.links] == [
        ("runtime_calls", "resource:caller", "resource:target")
    ]
