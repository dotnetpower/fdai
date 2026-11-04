"""Tests for Area D (Items 17-20): Scenario branch & What-If digital twin simulation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fdai.core.ontology_platform.advanced_decision_functions import (
    RecoveryFeasibilityEvidence,
    SpofExposureEvidence,
)
from fdai.core.ontology_platform.digital_twin_simulation import (
    CounterfactualOptionSpec,
    build_workflow_topology_preview,
    compare_counterfactual_options,
    simulate_workflow_on_scenario_branch,
    validate_chaos_spof_recovery_readiness,
)
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.query_receipt_authority import SecuredQueryReceiptAuthority
from fdai.core.ontology_platform.scenario_branch import OntologyScenarioChangeSet
from fdai.core.operational_context import (
    AuthenticatedPrincipalContext,
    OperationalEvidenceMaterial,
    OperationalEvidenceReadRequest,
    OperationalEvidenceReadService,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
RELEASE = "sha256:" + "a" * 64
PRINCIPAL_SCOPE = "sha256:" + "c" * 64


class _EvidenceSource:
    async def collect(self, request: OperationalEvidenceReadRequest) -> OperationalEvidenceMaterial:
        return OperationalEvidenceMaterial(
            ontology_release_digest=request.ontology_release_digest,
            catalog_revision=request.catalog_revision,
            purpose=request.purpose,
            scope=request.scope,
            cutoff=request.cutoff,
        )


async def _bundle():
    authority = SecuredQueryReceiptAuthority()
    result = await OperationalEvidenceReadService(
        source=_EvidenceSource(),
        clock=lambda: NOW,
    ).read(
        OperationalEvidenceReadRequest(
            ontology_release_digest=RELEASE,
            catalog_revision="catalog-r1",
            purpose="scenario-review",
            scope=("db-1",),
            cutoff=NOW,
        ),
        authenticated_context=AuthenticatedPrincipalContext(
            principal_ref="principal-1",
            principal_scope_digest=PRINCIPAL_SCOPE,
            purpose="scenario-review",
            receipt_authority=authority,
            invocation_context=FunctionInvocationContext(
                caller_agent="Bragi",
                caller_role="reader",
                purposes=("scenario-review",),
            ),
            verification_context=authority.verification_context,
        ),
    )
    return result.bundle


def _metadata() -> dict[str, object]:
    return StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="inventory-provider",
        source_revision="generation-1",
        effective_at=NOW,
        recorded_at=NOW,
        evidence_cutoff=NOW,
        freshness_ceiling_seconds=3600,
        completeness=1.0,
        synthetic=False,
        evidence_refs=("inventory-generation:generation-1",),
    ).to_mapping()


def _base_snapshot() -> OntologyGraphSnapshot:
    long_ago = (NOW - timedelta(days=30)).isoformat()
    objects = (
        OntologyObjectRecord(
            id="db-1",
            object_type="Resource",
            properties={
                "id": "db-1",
                "type": "compute",
                "properties": {STATE_FACT_METADATA_PROPERTY: _metadata()},
            },
        ),
        OntologyObjectRecord(
            id="api-1",
            object_type="Resource",
            properties={"id": "api-1", "type": "compute"},
        ),
        OntologyObjectRecord(
            id="wl-1",
            object_type="Workload",
            properties={
                "id": "wl-1",
                "name": "wl-1",
                "workload_kind": "service",
                "effective_from": long_ago,
                "source_ref": "catalog",
            },
        ),
        OntologyObjectRecord(
            id="svc-1",
            object_type="BusinessService",
            properties={
                "id": "svc-1",
                "name": "svc-1",
                "criticality": "critical",
                "effective_from": long_ago,
                "source_ref": "catalog",
            },
        ),
    )
    links = (
        OntologyLinkRecord("depends_on", "api-1", "db-1"),
        OntologyLinkRecord("workload_runs_on", "wl-1", "api-1"),
        OntologyLinkRecord("implemented_by", "svc-1", "wl-1"),
    )
    return OntologyGraphSnapshot(objects=objects, links=links, source_complete=True)


async def test_items_17_18_19_scenario_branch_counterfactuals_and_topology_preview() -> None:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    bundle = await _bundle()
    base = _base_snapshot()

    # Option A: drain/detach api-1 from db-1 -> lowers blast radius score on db-1
    drain_changes = OntologyScenarioChangeSet(
        delete_link_keys=(("api-1", "depends_on", "db-1"),),
        upsert_objects=(
            OntologyObjectRecord(
                id="svc-low",
                object_type="BusinessService",
                properties={
                    "id": "svc-low",
                    "name": "svc-low",
                    "criticality": "low",
                    "effective_from": (NOW - timedelta(days=30)).isoformat(),
                    "source_ref": "catalog",
                },
            ),
            OntologyObjectRecord(
                id="wl-db",
                object_type="Workload",
                properties={
                    "id": "wl-db",
                    "name": "wl-db",
                    "workload_kind": "service",
                    "effective_from": (NOW - timedelta(days=30)).isoformat(),
                    "source_ref": "catalog",
                },
            ),
        ),
        upsert_links=(
            OntologyLinkRecord("workload_runs_on", "wl-db", "db-1"),
            OntologyLinkRecord("implemented_by", "svc-low", "wl-db"),
        ),
    )
    # Option B: no detachment -> high blast score remains
    noop_changes = OntologyScenarioChangeSet()

    sim = await simulate_workflow_on_scenario_branch(
        branch_id="branch-drain",
        evidence_bundle=bundle,
        base=base,
        changes=drain_changes,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        target_ref="db-1",
        max_tier="low",
        at=NOW,
    )
    assert sim.execution_authority is False
    assert sim.score_delta < 0
    assert sim.gate_satisfied_after_change is True

    comparison = await compare_counterfactual_options(
        evidence_bundle=bundle,
        base=base,
        options=(
            CounterfactualOptionSpec("opt-in-place", "branch-inplace", 0.9, noop_changes),
            CounterfactualOptionSpec("opt-drain-first", "branch-drain", 0.85, drain_changes),
        ),
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        target_ref="db-1",
        max_tier="low",
        at=NOW,
    )
    assert comparison.recommended_option_id == "opt-drain-first"
    assert comparison.ranked_outcomes[0].option_id == "opt-drain-first"

    preview = await build_workflow_topology_preview(
        branch_id="branch-drain",
        evidence_bundle=bundle,
        base=base,
        changes=drain_changes,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        target_ref="db-1",
        max_tier="low",
        at=NOW,
    )
    assert preview.read_only is True
    assert preview.added_object_ids == ("svc-low", "wl-db")
    assert preview.deleted_link_count == 1
    assert preview.gate_satisfied_before is False
    assert preview.gate_satisfied_after is True


def test_item20_chaos_spof_recovery_readiness_validation() -> None:
    spof_ev = SpofExposureEvidence(
        zone_redundant=False,
        backup_verified=True,
        alternate_path_count=0,
        critical_dependent_count=2,
        observed_at=NOW,
    )
    ready_rec = RecoveryFeasibilityEvidence(
        estimated_rto_minutes=10.0,
        target_rto_minutes=15.0,
        estimated_rpo_minutes=2.0,
        target_rpo_minutes=5.0,
        rehearsal_verified=True,
        observed_at=NOW,
    )
    receipt = validate_chaos_spof_recovery_readiness(
        target_ref="db-1", spof_evidence=spof_ev, recovery_evidence=ready_rec
    )
    assert receipt.is_spof_candidate is True
    assert receipt.recovery_feasible is True
    assert receipt.chaos_drill_admitted is True

    unrehearsed = RecoveryFeasibilityEvidence(
        estimated_rto_minutes=10.0,
        target_rto_minutes=15.0,
        estimated_rpo_minutes=2.0,
        target_rpo_minutes=5.0,
        rehearsal_verified=False,
        observed_at=NOW,
    )
    blocked = validate_chaos_spof_recovery_readiness(
        target_ref="db-1", spof_evidence=spof_ev, recovery_evidence=unrehearsed
    )
    assert blocked.chaos_drill_admitted is False
    assert blocked.reason_code == "recovery_plan_not_feasible"
