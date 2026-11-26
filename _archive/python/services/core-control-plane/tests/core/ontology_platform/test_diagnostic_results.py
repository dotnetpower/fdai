"""Tests for immutable diagnostic result ontology projection."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.ontology_platform.diagnostic_results import (
    DiagnosticResultProjector,
    build_diagnostic_result_projection,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

_ROOT = Path(__file__).resolve().parents[5]
_MECHANISM_ID = "kubernetes_missing_dependency_reducer"
_RESOURCE_ID = "kubernetes.namespace/example"


def _receipt() -> dict[str, object]:
    return {
        "invocation_id": "logic-invocation:" + "a" * 64,
        "function_ref": {
            "kind": "function",
            "name": f"diagnostic.{_MECHANISM_ID}",
            "version": "1.0.0",
            "catalog_digest": "sha256:" + "b" * 64,
        },
        "caller_agent": "Heimdall",
        "input_digest": "sha256:" + "c" * 64,
        "output_digest": "sha256:" + "d" * 64,
    }


def _projection(
    *,
    decision: str = "hold",
    evidence: object = None,
    observed_at: datetime = datetime(2026, 8, 5, tzinfo=UTC),
):  # type: ignore[no-untyped-def]
    return build_diagnostic_result_projection(
        mechanism_id=_MECHANISM_ID,
        findings=[{"reason": "missing_service", "decision": decision}],
        evidence={"evidence_complete": True, "resources": evidence or []},
        evidence_ref="logic-invocation:" + "a" * 64,
        source_revision="sha256:" + "b" * 64,
        invocation_receipt=_receipt(),
        resource_ref=_RESOURCE_ID,
        observed_at=observed_at,
    )


def _store() -> InMemoryOntologyInstanceStore:
    catalog = load_ontology_catalog(
        _ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=_ROOT / "rule-catalog/probes",
    )
    return InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )


async def _seed_endpoints(store: InMemoryOntologyInstanceStore) -> None:
    await store.upsert_object(
        OntologyObjectRecord(
            id=f"diagnostic-mechanism:{_MECHANISM_ID}",
            object_type="DiagnosticMechanism",
            properties={
                "id": f"diagnostic-mechanism:{_MECHANISM_ID}",
                "mechanism_id": _MECHANISM_ID,
                "status": "semantic_generalized",
                "source_commits": ["a" * 40],
                "benchmark_measured": True,
                "semantic_generalized": True,
                "operationalized": False,
                "provider_validated": False,
                "action_validated": False,
                "outcome_validated": False,
                "azure_validated": False,
            },
        )
    )
    await store.upsert_object(
        OntologyObjectRecord(
            id=_RESOURCE_ID,
            object_type="Resource",
            properties={
                "id": _RESOURCE_ID,
                "type": "kubernetes.namespace",
                "properties": {},
            },
        )
    )


async def test_projects_complete_content_addressed_provenance_graph_idempotently() -> None:
    store = _store()
    await _seed_endpoints(store)
    projection = _projection()
    projector = DiagnosticResultProjector(store=store)

    await projector.project(projection)
    await projector.project(projection)

    graph = await store.query_objects(
        object_types=("DiagnosticEvidence", "DiagnosticFinding"),
        limit=10,
    )
    assert len(graph.objects) == 2
    assert all(item.revision == 1 for item in graph.objects)
    finding_id = next(item.id for item in graph.objects if item.object_type == "DiagnosticFinding")
    provenance = await store.traverse(root_ids=(finding_id,), max_depth=1, limit=10)
    assert {item.link_type for item in provenance.links} == {
        "diagnostic_finding_produced_by",
        "diagnostic_finding_derived_from",
        "diagnostic_finding_affects_resource",
    }


async def test_preserves_later_reobservation_as_a_distinct_immutable_graph() -> None:
    store = _store()
    await _seed_endpoints(store)
    projector = DiagnosticResultProjector(store=store)

    await projector.project(_projection())
    await projector.project(_projection(observed_at=datetime(2026, 8, 6, tzinfo=UTC)))

    graph = await store.query_objects(
        object_types=("DiagnosticEvidence", "DiagnosticFinding"),
        limit=10,
    )
    assert len(graph.objects) == 4


def test_rejects_non_hold_finding() -> None:
    with pytest.raises(ValueError, match="hold findings only"):
        _projection(decision="execute")


def test_rejects_naive_observation_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        build_diagnostic_result_projection(
            mechanism_id=_MECHANISM_ID,
            findings=[],
            evidence={},
            evidence_ref="evidence:example",
            source_revision="sha256:" + "b" * 64,
            invocation_receipt={**_receipt(), "invocation_id": "evidence:example"},
            resource_ref=_RESOURCE_ID,
            observed_at=datetime(2026, 8, 5),
        )


def test_rejects_oversized_evidence() -> None:
    with pytest.raises(ValueError, match="byte limit"):
        _projection(evidence=[{"value": "x" * 1_000_001}])
