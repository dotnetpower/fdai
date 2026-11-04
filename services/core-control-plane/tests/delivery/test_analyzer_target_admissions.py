"""Tests for analyzer target state-fact decision-evidence admission issuance (#2591)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fdai.delivery import analyzer_tick_cli_composition as analyzer_composition
from fdai.delivery.analyzer_inventory import AnalyzerInventorySources
from fdai.delivery.analyzer_target_admissions import (
    AnalyzerTargetDecisionEvidenceAdmissionProvider,
    AnalyzerTargetStateFactAdmissionIssuer,
)
from fdai.delivery.analyzer_targets import (
    ANALYZER_TARGET_EVIDENCE_PURPOSE,
    SKIP_STALE_STATE_FACT,
    SKIP_UNUSABLE_STATE_FACT,
    SKIP_UNVERIFIED_STATE_FACT,
    resolve_analyzer_targets,
)
from fdai.delivery.analyzer_tick_cli_composition import (
    build_decision_evidence_admission_provider,
)
from fdai.delivery.persistence.state_store_decision_evidence import (
    decision_evidence_state_key,
    parse_decision_evidence_record,
)
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyInstanceStore,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.ontology_query import content_digest

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _state_fact(
    *,
    observed_at: datetime = NOW,
    conflicts: tuple[str, ...] = (),
    synthetic: bool = False,
    completeness: float = 1.0,
    lane: StateFactLane = StateFactLane.OBSERVED,
    authority: StateFactAuthority = StateFactAuthority.PROVIDER,
    source_identity: str = "inventory-provider",
    source_revision: str = "generation-1",
    freshness_ceiling_seconds: int = 300,
) -> dict[str, object]:
    return StateFactMetadata(
        lane=lane,
        authority=authority,
        source_identity=source_identity,
        source_revision=source_revision,
        effective_at=observed_at,
        recorded_at=observed_at,
        evidence_cutoff=observed_at,
        freshness_ceiling_seconds=freshness_ceiling_seconds,
        completeness=completeness,
        synthetic=synthetic,
        conflicts=conflicts,
        evidence_refs=(f"inventory-generation:{source_revision}",),
    ).to_mapping()


def _resource(
    resource_id: str,
    resource_type: str,
    *,
    state_fact: Mapping[str, object] | None = None,
    property_keyed: bool = False,
    observed_state: str | None = None,
) -> OntologyObjectRecord:
    provider_properties: dict[str, Any] = {}
    if observed_state is not None:
        provider_properties["state"] = observed_state
    if state_fact is not None:
        provider_properties[STATE_FACT_METADATA_PROPERTY] = (
            {"state": dict(state_fact)} if property_keyed else dict(state_fact)
        )
    return OntologyObjectRecord(
        id=resource_id,
        object_type="Resource",
        properties={
            "id": resource_id,
            "type": resource_type,
            "properties": provider_properties,
        },
    )


class _StubInventoryStore:
    def __init__(
        self,
        objects: Sequence[OntologyObjectRecord] = (),
        *,
        source_generation: str | None = "generation-1",
        source_complete: bool = True,
        truncated: bool = False,
    ) -> None:
        self._objects = tuple(objects)
        self._source_generation = source_generation
        self._source_complete = source_complete
        self._truncated = truncated

    async def query_objects(
        self,
        *,
        object_types: Sequence[str] = (),
        object_ids: Sequence[str] = (),
        property_equals: Mapping[str, Any] | None = None,
        property_text_in: Mapping[str, Sequence[str]] | None = None,
        limit: int = 100,
        include_relationships: bool = True,
    ) -> OntologyGraphSnapshot:
        del object_types, object_ids, property_equals, include_relationships
        objects = self._objects
        if property_text_in is not None:
            objects = tuple(
                record
                for record in objects
                if all(
                    record.properties.get(key) in values for key, values in property_text_in.items()
                )
            )
        return OntologyGraphSnapshot(
            objects=objects[:limit],
            truncated=self._truncated or len(objects) > limit,
            source_complete=self._source_complete,
            source_generation=self._source_generation,
        )


class _StubProviderReferenceReader:
    def __init__(
        self,
        resources: Mapping[str, ResourceRecord],
        *,
        snapshot_id: str | None = "generation-1",
    ) -> None:
        self._resources = dict(resources)
        self._snapshot_id = snapshot_id

    async def read_active_resources(
        self,
        *,
        resource_ids: tuple[str, ...],
    ) -> tuple[str | None, Mapping[str, ResourceRecord]]:
        return (
            self._snapshot_id,
            {
                resource_id: self._resources[resource_id]
                for resource_id in resource_ids
                if resource_id in self._resources
            },
        )

    async def read_active_resources_by_provider_refs(
        self,
        *,
        provider_refs: tuple[str, ...],
    ) -> tuple[str | None, Mapping[str, ResourceRecord]]:
        by_ref = {
            (record.provider_ref or "").casefold(): record for record in self._resources.values()
        }
        return (
            self._snapshot_id,
            {ref: by_ref[ref] for ref in provider_refs if ref in by_ref},
        )


@pytest.mark.asyncio
async def test_issuer_produces_and_retains_admission_once_with_atomic_audit_and_admits_aks() -> (
    None
):
    aks_fact = _state_fact()
    vm_fact = _state_fact()
    inventory_store = _StubInventoryStore(
        (
            _resource("res-aks-1", "kubernetes-cluster", state_fact=aks_fact),
            _resource(
                "res-vm-1",
                "compute.vm",
                state_fact=vm_fact,
                property_keyed=True,
                observed_state="Running",
            ),
        )
    )
    provider_refs = _StubProviderReferenceReader(
        {
            "res-aks-1": ResourceRecord(
                resource_id="res-aks-1",
                type="kubernetes-cluster",
                props={STATE_FACT_METADATA_PROPERTY: dict(aks_fact)},
                provider_ref="/providers/example/resources/res-aks-1",
                last_seen=NOW.isoformat(),
            ),
            "res-vm-1": ResourceRecord(
                resource_id="res-vm-1",
                type="compute.vm",
                props={"powerState": "Running"},
                provider_ref="/providers/example/resources/res-vm-1",
                last_seen=NOW.isoformat(),
            ),
        }
    )
    state_store = InMemoryStateStore()
    issuer = AnalyzerTargetStateFactAdmissionIssuer(
        inventory_store=inventory_store,
        state_store=state_store,
        provider_references=provider_refs,
        clock=lambda: NOW,
    )
    provider = AnalyzerTargetDecisionEvidenceAdmissionProvider(
        store=state_store,
        issuer=issuer,
        clock=lambda: NOW,
    )

    resolution = await resolve_analyzer_targets(
        configured=(),
        store=cast(OntologyInstanceStore, inventory_store),
        now=NOW,
        decision_evidence=provider,
        provider_references=provider_refs,
    )

    assert [target.resource_ref for target in resolution.targets] == ["res-aks-1", "res-vm-1"]
    assert resolution.discovered == 2
    assert resolution.skipped_reasons == ()
    audit_entries = tuple(state_store.audit_entries)
    assert len(audit_entries) == 2
    assert all(
        record["entry"]["kind"] == "decision-evidence.admission-retained"
        and record["entry"]["mode"] == "shadow"
        and record["entry"]["execution_authority"] is False
        and record["entry"]["promotion_authority"] is False
        for record in audit_entries
    )
    assert await state_store.verify_chain() is True

    # Second tick over the same generation reuses retained records without duplicate writes.
    second_report = await issuer.issue_eligible(now=NOW)
    assert second_report.retained_count == 0
    assert second_report.already_retained_count == 2
    assert len(tuple(state_store.audit_entries)) == 2

    # Verify stored record shape and digests.
    evidence_digest = content_digest({"resource_id": "res-aks-1", "state_fact": aks_fact})
    scope_digest = content_digest(
        {"resource_id": "res-aks-1", "resource_type": "kubernetes-cluster"}
    )
    key = decision_evidence_state_key(
        evidence_digest=evidence_digest,
        scope_digest=scope_digest,
        purpose_id=ANALYZER_TARGET_EVIDENCE_PURPOSE,
        source_revision="generation-1",
    )
    raw_record = await state_store.read_state(key)
    assert raw_record is not None
    parsed = parse_decision_evidence_record(raw_record)
    assert parsed.admission.purpose_id == ANALYZER_TARGET_EVIDENCE_PURPOSE
    assert parsed.admission.execution_authority is False
    assert parsed.admission.promotion_authority is False


@pytest.mark.asyncio
async def test_local_tick_still_holds_stale_conflicting_synthetic_and_unverified_state_facts() -> (
    None
):
    fresh_aks = _resource("res-aks-fresh", "kubernetes-cluster", state_fact=_state_fact())
    stale_aks = _resource(
        "res-aks-stale",
        "kubernetes-cluster",
        state_fact=_state_fact(observed_at=NOW - timedelta(seconds=301)),
    )
    conflicting_aks = _resource(
        "res-aks-conflict",
        "kubernetes-cluster",
        state_fact=_state_fact(conflicts=("powerState",)),
    )
    synthetic_aks = _resource(
        "res-aks-synthetic",
        "kubernetes-cluster",
        state_fact=_state_fact(synthetic=True),
    )
    unverified_aks = _resource(
        "res-aks-unverified",
        "kubernetes-cluster",
        state_fact=_state_fact(),
    )
    inventory_store = _StubInventoryStore(
        (fresh_aks, stale_aks, conflicting_aks, synthetic_aks, unverified_aks)
    )
    # Only res-aks-fresh has a matching active provider reference during verifier issuance;
    # res-aks-unverified is omitted from the verifier's active snapshot so it gets no admission.
    verifier_refs = _StubProviderReferenceReader(
        {
            "res-aks-fresh": ResourceRecord(
                resource_id="res-aks-fresh",
                type="kubernetes-cluster",
                props={STATE_FACT_METADATA_PROPERTY: _state_fact()},
                provider_ref="/providers/example/resources/res-aks-fresh",
                last_seen=NOW.isoformat(),
            ),
        }
    )
    resolver_refs = _StubProviderReferenceReader(
        {
            "res-aks-fresh": ResourceRecord(
                resource_id="res-aks-fresh",
                type="kubernetes-cluster",
                props={STATE_FACT_METADATA_PROPERTY: _state_fact()},
                provider_ref="/providers/example/resources/res-aks-fresh",
                last_seen=NOW.isoformat(),
            ),
            "res-aks-unverified": ResourceRecord(
                resource_id="res-aks-unverified",
                type="kubernetes-cluster",
                props={STATE_FACT_METADATA_PROPERTY: _state_fact()},
                provider_ref="/providers/example/resources/res-aks-unverified",
                last_seen=NOW.isoformat(),
            ),
        }
    )
    state_store = InMemoryStateStore()
    issuer = AnalyzerTargetStateFactAdmissionIssuer(
        inventory_store=inventory_store,
        state_store=state_store,
        provider_references=verifier_refs,
        clock=lambda: NOW,
    )
    provider = AnalyzerTargetDecisionEvidenceAdmissionProvider(
        store=state_store,
        issuer=issuer,
        clock=lambda: NOW,
    )

    resolution = await resolve_analyzer_targets(
        configured=(),
        store=cast(OntologyInstanceStore, inventory_store),
        now=NOW,
        decision_evidence=provider,
        provider_references=resolver_refs,
    )

    assert [target.resource_ref for target in resolution.targets] == ["res-aks-fresh"]
    assert dict(resolution.skipped_reason_counts) == {
        SKIP_STALE_STATE_FACT: 1,
        SKIP_UNUSABLE_STATE_FACT: 2,
        SKIP_UNVERIFIED_STATE_FACT: 1,
    }
    assert len(tuple(state_store.audit_entries)) == 1


@pytest.mark.asyncio
async def test_admission_provider_covers_missing_expired_and_mismatched_scope_cases() -> None:
    aks_fact = _state_fact(freshness_ceiling_seconds=60)
    inventory_store = _StubInventoryStore(
        (_resource("res-aks-1", "kubernetes-cluster", state_fact=aks_fact),)
    )
    provider_refs = _StubProviderReferenceReader(
        {
            "res-aks-1": ResourceRecord(
                resource_id="res-aks-1",
                type="kubernetes-cluster",
                props={STATE_FACT_METADATA_PROPERTY: dict(aks_fact)},
                provider_ref="/providers/example/resources/res-aks-1",
                last_seen=NOW.isoformat(),
            )
        }
    )
    clock = [NOW]
    state_store = InMemoryStateStore()
    issuer = AnalyzerTargetStateFactAdmissionIssuer(
        inventory_store=inventory_store,
        state_store=state_store,
        provider_references=provider_refs,
        clock=lambda: clock[0],
    )
    provider = AnalyzerTargetDecisionEvidenceAdmissionProvider(
        store=state_store,
        issuer=issuer,
        clock=lambda: clock[0],
    )

    evidence_digest = content_digest({"resource_id": "res-aks-1", "state_fact": aks_fact})
    valid_scope = content_digest(
        {"resource_id": "res-aks-1", "resource_type": "kubernetes-cluster"}
    )
    mismatched_scope = content_digest({"resource_id": "res-aks-1", "resource_type": "compute.vm"})

    # 1. Mismatched scope is rejected even after syncing eligible inventory records.
    assert (
        await provider.admit(
            evidence_digest=evidence_digest,
            scope_digest=mismatched_scope,
            purpose_id=ANALYZER_TARGET_EVIDENCE_PURPOSE,
            source_revision="generation-1",
        )
        is None
    )

    # 2. Matching scope is admitted while current.
    admitted = await provider.admit(
        evidence_digest=evidence_digest,
        scope_digest=valid_scope,
        purpose_id=ANALYZER_TARGET_EVIDENCE_PURPOSE,
        source_revision="generation-1",
    )
    assert admitted is not None
    assert admitted.scope_digest == valid_scope

    # 3. Missing evidence digest returns None.
    missing_digest = content_digest({"resource_id": "res-missing", "state_fact": aks_fact})
    assert (
        await provider.admit(
            evidence_digest=missing_digest,
            scope_digest=valid_scope,
            purpose_id=ANALYZER_TARGET_EVIDENCE_PURPOSE,
            source_revision="generation-1",
        )
        is None
    )

    # 4. Expired admission (clock past valid_until) returns None and fails closed.
    clock[0] = NOW + timedelta(seconds=61)
    assert (
        await provider.admit(
            evidence_digest=evidence_digest,
            scope_digest=valid_scope,
            purpose_id=ANALYZER_TARGET_EVIDENCE_PURPOSE,
            source_revision="generation-1",
        )
        is None
    )


@pytest.mark.asyncio
async def test_composition_builder_wires_state_fact_issuer_when_inventory_is_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SimpleNamespace(aclose=AsyncMock())
    inventory = AnalyzerInventorySources(
        projection=SimpleNamespace(),  # type: ignore[arg-type]
        provider_references=SimpleNamespace(),  # type: ignore[arg-type]
    )
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://example/fdai")
    monkeypatch.setattr(analyzer_composition, "PostgresStateStore", lambda **_: store)

    provider = build_decision_evidence_admission_provider(inventory=inventory)
    assert provider is not None
    assert isinstance(provider, AnalyzerTargetDecisionEvidenceAdmissionProvider)

    await provider.aclose()
    store.aclose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_issuer_rejects_uncorroborated_or_mismatched_active_snapshot_state_facts() -> None:
    aks_fact = _state_fact()
    inventory_store = _StubInventoryStore(
        (_resource("res-aks-1", "kubernetes-cluster", state_fact=aks_fact),)
    )
    state_store = InMemoryStateStore()

    # 1. Missing provider_references refuses non-pod issuance.
    unbound_issuer = AnalyzerTargetStateFactAdmissionIssuer(
        inventory_store=inventory_store,
        state_store=state_store,
        provider_references=None,
        clock=lambda: NOW,
    )
    report_unbound = await unbound_issuer.issue_eligible(now=NOW)
    assert report_unbound.retained_count == 0
    assert dict(report_unbound.skipped_reason_counts) == {"provider_identity_unavailable": 1}

    # 2. Missing last_seen or missing active state metadata/operational state refuses issuance.
    missing_corroboration_refs = _StubProviderReferenceReader(
        {
            "res-aks-1": ResourceRecord(
                resource_id="res-aks-1",
                type="kubernetes-cluster",
                provider_ref="/providers/example/resources/res-aks-1",
            )
        }
    )
    missing_corroboration_issuer = AnalyzerTargetStateFactAdmissionIssuer(
        inventory_store=inventory_store,
        state_store=state_store,
        provider_references=missing_corroboration_refs,
        clock=lambda: NOW,
    )
    report_missing = await missing_corroboration_issuer.issue_eligible(now=NOW)
    assert report_missing.retained_count == 0
    assert dict(report_missing.skipped_reason_counts) == {"unverified_state_fact_corroboration": 1}

    # 3. Active snapshot last_seen mismatch with evidence_cutoff refuses issuance.
    mismatched_last_seen_refs = _StubProviderReferenceReader(
        {
            "res-aks-1": ResourceRecord(
                resource_id="res-aks-1",
                type="kubernetes-cluster",
                props={STATE_FACT_METADATA_PROPERTY: dict(aks_fact)},
                provider_ref="/providers/example/resources/res-aks-1",
                last_seen=(NOW - timedelta(seconds=10)).isoformat(),
            )
        }
    )
    mismatch_issuer = AnalyzerTargetStateFactAdmissionIssuer(
        inventory_store=inventory_store,
        state_store=state_store,
        provider_references=mismatched_last_seen_refs,
        clock=lambda: NOW,
    )
    report_mismatch = await mismatch_issuer.issue_eligible(now=NOW)
    assert report_mismatch.retained_count == 0
    assert dict(report_mismatch.skipped_reason_counts) == {"unverified_state_fact_corroboration": 1}

    # 4. Active snapshot state_fact metadata mismatch refuses issuance.
    mismatched_meta_refs = _StubProviderReferenceReader(
        {
            "res-aks-1": ResourceRecord(
                resource_id="res-aks-1",
                type="kubernetes-cluster",
                props={
                    STATE_FACT_METADATA_PROPERTY: _state_fact(
                        source_identity="different-source",
                    )
                },
                provider_ref="/providers/example/resources/res-aks-1",
                last_seen=NOW.isoformat(),
            )
        }
    )
    meta_mismatch_issuer = AnalyzerTargetStateFactAdmissionIssuer(
        inventory_store=inventory_store,
        state_store=state_store,
        provider_references=mismatched_meta_refs,
        clock=lambda: NOW,
    )
    report_meta_mismatch = await meta_mismatch_issuer.issue_eligible(now=NOW)
    assert report_meta_mismatch.retained_count == 0
    assert dict(report_meta_mismatch.skipped_reason_counts) == {
        "unverified_state_fact_corroboration": 1
    }

    # 5. Operational-state fallback without projection properties.state is rejected.
    vm_without_projected_state = _StubInventoryStore(
        (_resource("res-vm-1", "compute.vm", state_fact=aks_fact),)
    )
    vm_refs = _StubProviderReferenceReader(
        {
            "res-vm-1": ResourceRecord(
                resource_id="res-vm-1",
                type="compute.vm",
                props={"powerState": "Running"},
                provider_ref="/providers/example/resources/res-vm-1",
                last_seen=NOW.isoformat(),
            )
        }
    )
    vm_no_state_issuer = AnalyzerTargetStateFactAdmissionIssuer(
        inventory_store=vm_without_projected_state,
        state_store=state_store,
        provider_references=vm_refs,
        clock=lambda: NOW,
    )
    report_vm_no_state = await vm_no_state_issuer.issue_eligible(now=NOW)
    assert report_vm_no_state.retained_count == 0
    assert dict(report_vm_no_state.skipped_reason_counts) == {
        "unverified_state_fact_corroboration": 1
    }

    # 6. State-bearing kubernetes.pod candidates are held because pods have no active snapshot.
    pod_inventory = _StubInventoryStore(
        (_resource("scenario/pod-1", "kubernetes.pod", state_fact=aks_fact),)
    )
    pod_issuer = AnalyzerTargetStateFactAdmissionIssuer(
        inventory_store=pod_inventory,
        state_store=state_store,
        provider_references=vm_refs,
        clock=lambda: NOW,
    )
    report_pod = await pod_issuer.issue_eligible(now=NOW)
    assert report_pod.retained_count == 0
    assert dict(report_pod.skipped_reason_counts) == {"unverified_provider_identity": 1}


@pytest.mark.asyncio
async def test_issuer_admits_runtime_projection_with_availability_metadata_and_power_state() -> (
    None
):
    inv_fact = _state_fact(
        source_identity="inventory-provider",
        source_revision="generation-1",
    )
    inventory_store = _StubInventoryStore(
        (
            _resource(
                "res-aks-runtime",
                "kubernetes-cluster",
                state_fact=inv_fact,
                property_keyed=True,
                observed_state="Stopped",
            ),
        ),
        source_complete=False,
    )
    provider_refs = _StubProviderReferenceReader(
        {
            "res-aks-runtime": ResourceRecord(
                resource_id="res-aks-runtime",
                type="kubernetes-cluster",
                props={
                    STATE_FACT_METADATA_PROPERTY: {
                        "availabilityState": _state_fact(
                            source_identity="azure-resource-health",
                            source_revision="arh-1",
                        )
                    },
                    "properties": {"powerState": {"code": "Stopped"}},
                },
                provider_ref="/providers/example/resources/res-aks-runtime",
                last_seen=NOW.isoformat(),
            )
        }
    )
    state_store = InMemoryStateStore()
    issuer = AnalyzerTargetStateFactAdmissionIssuer(
        inventory_store=inventory_store,
        state_store=state_store,
        provider_references=provider_refs,
        clock=lambda: NOW,
    )
    report = await issuer.issue_eligible(now=NOW)
    assert report.retained_count == 1
    assert report.skipped_reason_counts == ()
