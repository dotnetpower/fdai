"""Reviewed ontology gate configuration and its end-to-end composition."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.core.ontology_platform.workflow_gate_config import load_ontology_gate_config
from fdai.core.workflow import OntologyFunctionGateEvaluator
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.runtime.control_loop_support import build_ontology_gate_reader
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore, InMemoryStateStore
from tests.core.ontology_platform.test_decision_evidence_readers import _metadata

REPO_ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def _shipped() -> dict[str, object]:
    return yaml.safe_load((REPO_ROOT / "config" / "workflow-ontology-gates.yaml").read_text())


def test_shipped_configuration_configures_the_blast_radius_and_change_risk_gates() -> None:
    config = load_ontology_gate_config(_shipped())

    assert config.max_reading_age == timedelta(seconds=300)
    assert config.blast_radius is not None and config.blast_radius.max_tier == "medium"
    assert config.change_risk is not None and config.change_risk.max_tier == "medium"
    assert config.gate_arguments() == {
        "decision.blast_radius": {"max_tier": "medium"},
        "decision.change_risk": {"max_tier": "medium"},
    }


def test_cost_of_delay_is_not_a_configurable_gate() -> None:
    raw = _shipped()
    raw["decision.cost_of_delay"] = {"delay_hours": 24}

    with pytest.raises(ValueError, match="unknown key"):
        load_ontology_gate_config(raw)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw.update(schema_version="2.0"), "schema_version"),
        (lambda raw: raw.update(unknown=1), "unknown key"),
        (lambda raw: raw.update(max_reading_age_seconds=0), "max_reading_age_seconds"),
        (lambda raw: raw.update(max_reading_age_seconds=True), "max_reading_age_seconds"),
        (lambda raw: raw["decision.blast_radius"].update(max_tier="critical"), "max_tier"),
        (lambda raw: raw["decision.blast_radius"].update(max_depth=6), "max_depth"),
        (lambda raw: raw["decision.change_risk"].update(dry_run_lookback_days=0), "look-back"),
    ],
)
def test_malformed_configuration_is_rejected(mutate, message: str) -> None:
    raw = _shipped()
    mutate(raw)

    with pytest.raises(ValueError, match=message):
        load_ontology_gate_config(raw)


def _catalog():
    return load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )


def _release(catalog, function_types):
    return build_ontology_release(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        action_types=catalog.action_types,
        interface_types=catalog.interface_types,
        function_types=function_types,
    )


async def _low_risk_graph(catalog) -> InMemoryOntologyInstanceStore:
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types, link_types=catalog.link_types
    )
    long_ago = NOW - timedelta(days=30)
    for record in (
        OntologyObjectRecord(
            id="db",
            object_type="Resource",
            properties={
                "id": "db",
                "type": "compute",
                "properties": {"state_fact_metadata": _metadata()},
            },
        ),
        OntologyObjectRecord(
            id="w",
            object_type="Workload",
            properties={
                "id": "w",
                "name": "w",
                "workload_kind": "service",
                "effective_from": long_ago,
                "source_ref": "catalog",
            },
        ),
        OntologyObjectRecord(
            id="s",
            object_type="BusinessService",
            properties={
                "id": "s",
                "name": "s",
                "criticality": "low",
                "effective_from": long_ago,
                "source_ref": "catalog",
            },
        ),
    ):
        await store.upsert_object(record)
    await store.upsert_link(
        OntologyLinkRecord(link_type="workload_runs_on", from_id="w", to_id="db")
    )
    await store.upsert_link(OntologyLinkRecord(link_type="implemented_by", from_id="s", to_id="w"))
    return store


async def _gate(bound, name: str, *, target: str = "db", at: datetime = NOW) -> bool:
    reader, age = bound
    evaluator = OntologyFunctionGateEvaluator(reader=reader, max_reading_age=age)
    return await evaluator.evaluate_context(
        rule_id=f"ontology-function:{name}",
        step_id="gate",
        process_id="process-1",
        target_resource_id=target,
        at=at,
    )


def _bind(catalog, store, clock):
    return build_ontology_gate_reader(
        catalog_root=REPO_ROOT / "rule-catalog",
        ontology_store=store,
        ontology_release=_release(catalog, operational_function_types(catalog.function_types)),
        audit_store=InMemoryStateStore(),
        environment={},
        clock=clock,
    )


async def test_composition_opens_a_configured_gate_end_to_end_for_complete_evidence() -> None:
    catalog = _catalog()
    store = await _low_risk_graph(catalog)
    bound = _bind(catalog, store, lambda: NOW)

    assert bound is not None
    assert await _gate(bound, "decision.blast_radius") is True
    # Change risk stays shut: no change feed, recovery plan, or dry run is observed.
    assert await _gate(bound, "decision.change_risk") is False
    # Cost of delay is a ranking signal, not a gate, so it is not registered.
    assert await _gate(bound, "decision.cost_of_delay") is False
    assert await _gate(bound, "decision.blast_radius", target="missing") is False


async def test_a_stale_graph_keeps_the_gate_shut() -> None:
    catalog = _catalog()
    store = await _low_risk_graph(catalog)
    stale_at = NOW + timedelta(hours=2)
    bound = _bind(catalog, store, lambda: stale_at)

    assert bound is not None
    assert await _gate(bound, "decision.blast_radius", at=stale_at) is False


async def test_composition_binds_nothing_without_a_store_config_or_decision_release(
    tmp_path: Path,
) -> None:
    catalog = _catalog()
    store = await _low_risk_graph(catalog)
    kwargs = {
        "ontology_store": store,
        "audit_store": InMemoryStateStore(),
        "environment": {},
    }
    release = _release(catalog, operational_function_types(catalog.function_types))

    assert (
        build_ontology_gate_reader(
            catalog_root=REPO_ROOT / "rule-catalog",
            ontology_release=release,
            **{**kwargs, "ontology_store": None},
        )
        is None
    )
    assert (
        build_ontology_gate_reader(
            catalog_root=tmp_path / "rule-catalog", ontology_release=release, **kwargs
        )
        is None
    )
    # A release without the decision functions cannot register them, so no gate binds.
    assert (
        build_ontology_gate_reader(
            catalog_root=REPO_ROOT / "rule-catalog",
            ontology_release=_release(catalog, ()),
            **kwargs,
        )
        is None
    )
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "workflow-ontology-gates.yaml").write_text("schema_version: '9'\n")
    assert (
        build_ontology_gate_reader(
            catalog_root=tmp_path / "rule-catalog", ontology_release=release, **kwargs
        )
        is None
    )


async def test_advanced_decision_gates_bind_and_evaluate_end_to_end(tmp_path: Path) -> None:
    catalog = _catalog()
    store = await _low_risk_graph(catalog)
    await store.upsert_object(
        OntologyObjectRecord(
            id="db",
            object_type="Resource",
            properties={
                "id": "db",
                "type": "compute",
                "properties": {
                    "state_fact_metadata": _metadata(),
                    "zone_redundant": True,
                    "backup_verified": True,
                    "alternate_path_count": 2,
                    "critical_dependent_count": 1,
                    "remaining_budget_ratio": 0.5,
                    "burn_rate_per_hour": 0.05,
                },
            },
        )
    )
    await store.upsert_object(
        OntologyObjectRecord(
            id="plan-1",
            object_type="RecoveryPlan",
            properties={
                "id": "plan-1",
                "strategy": "rollback",
                "status": "ready",
                "workflow_ref": "wf@1.0.0",
                "action_type_refs": ["ops.scale-in@1.0.0"],
                "compensation_order": ["a"],
                "impact_envelope_id": "env",
                "recovery_objective_ref": "obj",
                "verification_probes": ["target_healthy"],
                "last_rehearsed_at": NOW - timedelta(hours=1),
                "expires_at": NOW + timedelta(days=5),
            },
        )
    )
    await store.upsert_link(
        OntologyLinkRecord(link_type="recovery_targets_resource", from_id="plan-1", to_id="db")
    )

    (tmp_path / "config").mkdir()
    (tmp_path / "rule-catalog").mkdir()
    (tmp_path / "config" / "workflow-ontology-gates.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "max_reading_age_seconds": 300,
                "decision.slo_exhaustion_eta": {"min_remaining_minutes": 120},
                "decision.change_collision": {"max_collisions": 0},
                "decision.recovery_feasibility": {"enabled": True},
                "decision.spof_exposure": {"max_tier": "low"},
            }
        )
    )
    release = _release(catalog, operational_function_types(catalog.function_types))
    bound = build_ontology_gate_reader(
        catalog_root=tmp_path / "rule-catalog",
        ontology_store=store,
        ontology_release=release,
        audit_store=InMemoryStateStore(),
        environment={},
        clock=lambda: NOW,
    )
    assert bound is not None
    assert await _gate(bound, "decision.slo_exhaustion_eta") is True
    assert await _gate(bound, "decision.change_collision") is True
    assert await _gate(bound, "decision.recovery_feasibility") is True
    assert await _gate(bound, "decision.spof_exposure") is True
