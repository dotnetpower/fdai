"""Tests for CatalogCausalGradeBridge wiring 55 scenarios behind E8 causal-grade receipts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fdai.core.rca.hypothesis import CausalHypothesisStatus
from fdai.delivery.azure.catalog_causal_grade_bridge import (
    TELEMETRY_TO_REVIEWED_MECHANISM,
    GradedScenarioExecutionReport,
)
from fdai.delivery.azure.catalog_causal_prediction_engine import (
    load_causal_prediction_scenario_catalog,
)
from fdai.delivery.azure.catalog_telemetry_mechanisms import CatalogTelemetryMechanism
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.runtime.causal_bindings import build_catalog_causal_grade_bridge
from fdai.shared.contracts.models import CausalEvidenceGrade
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

REPO_ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def test_every_telemetry_mechanism_maps_to_a_reviewed_catalog_mechanism() -> None:
    bridge = build_catalog_causal_grade_bridge(repo_root=REPO_ROOT)

    assert set(TELEMETRY_TO_REVIEWED_MECHANISM) == set(CatalogTelemetryMechanism)
    assert len(bridge.reviewed_mechanisms) >= 8
    for mech in CatalogTelemetryMechanism:
        spec = bridge.resolve_mechanism(mech)
        assert len(spec.refutation_reads) >= 2


def test_all_55_scenarios_grade_to_predictive_precedence_only_when_refutations_pass() -> None:
    bridge = build_catalog_causal_grade_bridge(repo_root=REPO_ROOT)
    catalog = load_causal_prediction_scenario_catalog(REPO_ROOT)

    assert len(catalog.scenarios) == 55
    for spec in catalog.scenarios.values():
        graded: GradedScenarioExecutionReport = bridge.execute_and_grade_scenario(
            spec, base_time=NOW
        )
        assert graded.hypothesis_supported is True
        assert graded.grade_receipt.grade is CausalEvidenceGrade.PREDICTIVE_PRECEDENCE
        assert (
            graded.report.causal_result.hypothesis_record.evidence_grade
            is CausalEvidenceGrade.PREDICTIVE_PRECEDENCE
        )
        assert (
            graded.report.causal_result.hypothesis_record.status is CausalHypothesisStatus.SUPPORTED
        )
        assert graded.execution_authority is False


def test_missing_or_refuting_reads_downgrade_scenario_hypothesis_to_association() -> None:
    bridge = build_catalog_causal_grade_bridge(repo_root=REPO_ROOT)
    catalog = load_causal_prediction_scenario_catalog(REPO_ROOT)
    spec = catalog.get_by_round("D001")
    reviewed = bridge.resolve_mechanism(spec.causal_mechanisms[0])

    unaccounted = bridge.execute_and_grade_scenario(
        spec,
        base_time=NOW,
        refutation_reads_run=(reviewed.refutation_reads[0],),
    )
    assert unaccounted.hypothesis_supported is False
    assert unaccounted.grade_receipt.grade is CausalEvidenceGrade.ASSOCIATION
    assert (
        unaccounted.report.causal_result.hypothesis_record.evidence_grade
        is CausalEvidenceGrade.ASSOCIATION
    )
    assert (
        unaccounted.report.causal_result.hypothesis_record.status
        is CausalHypothesisStatus.CANDIDATE
    )
    assert unaccounted.report.causal_result.hypothesis_record.closure is None

    refuted = bridge.execute_and_grade_scenario(
        spec,
        base_time=NOW,
        refuted_reads=(reviewed.refutation_reads[0],),
    )
    assert refuted.hypothesis_supported is False
    assert refuted.report.causal_result.hypothesis_record.status is CausalHypothesisStatus.CANDIDATE
    assert any(
        ref.startswith("refuted:")
        for ref in refuted.report.causal_result.hypothesis_record.refuting_refs
    )


async def test_graded_scenario_projects_into_runtime_ontology_store() -> None:
    ont_catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    store = InMemoryOntologyInstanceStore(
        object_types=ont_catalog.object_types,
        link_types=ont_catalog.link_types,
    )
    bridge = build_catalog_causal_grade_bridge(repo_root=REPO_ROOT, ontology_instance_store=store)
    spec = load_causal_prediction_scenario_catalog(REPO_ROOT).get_by_round("D001")
    graded = bridge.execute_and_grade_scenario(spec, base_time=NOW)
    finding = OntologyObjectRecord(
        id="finding:d001",
        object_type="Finding",
        properties={
            "id": "finding:d001",
            "rule_id": "rule.example",
            "resource_id": graded.report.causal_result.hypothesis_record.effect_ref,
            "severity": "critical",
            "evaluation_ts": NOW,
        },
    )
    projected = await bridge.project_graded_scenario(
        graded, finding_id="finding:d001", endpoint_objects=(finding,)
    )

    assert projected is True
    stored = await store.get_object(graded.report.causal_result.hypothesis_record.hypothesis_id)
    assert stored is not None
    assert stored.object_type == "CausalHypothesis"
    assert stored.properties["evidence_grade"] == "predictive_precedence"
