"""Tests for runtime diagnostic catalog projection composition."""

from __future__ import annotations

import copy
import json
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fdai.core.ontology_platform import CatalogOntologyProjection, CatalogOntologyProjector
from fdai.core.ontology_platform.diagnostic_ledger import validate_diagnostic_ledger
from fdai.core.ontology_platform.diagnostic_projection import (
    build_diagnostic_catalog_projection,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.runtime.catalog_ontology import (
    load_diagnostic_catalog_projection,
    project_catalog_ontology,
)
from fdai.shared.contracts.models import (
    OntologyDeclarationKind,
    OntologyLinkType,
    OntologyObjectType,
    Rule,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

_ROOT = Path(__file__).resolve().parents[4]


class _SyncRequiredOntologyStore(InMemoryOntologyInstanceStore):
    """Require declaration synchronization before accepting a projection write."""

    def __init__(
        self,
        *,
        object_types: Sequence[OntologyObjectType],
        link_types: Sequence[OntologyLinkType],
    ) -> None:
        super().__init__(object_types=object_types, link_types=link_types)
        self.catalog_synced = False

    async def sync_catalog(self) -> None:
        self.catalog_synced = True

    async def replace_subgraph(
        self,
        *,
        objects: Sequence[OntologyObjectRecord],
        links: Sequence[OntologyLinkRecord],
        previous_object_ids: Sequence[str] = (),
        previous_link_keys: Sequence[tuple[str, str, str]] = (),
    ) -> None:
        assert self.catalog_synced is True
        await super().replace_subgraph(
            objects=objects,
            links=links,
            previous_object_ids=previous_object_ids,
            previous_link_keys=previous_link_keys,
        )


def test_loads_all_mechanisms_and_independent_validation_receipts() -> None:
    projection = load_diagnostic_catalog_projection(_ROOT)

    assert len(projection.objects) == 488
    assert len(projection.links) == 427
    assert sum(item.object_type == "DiagnosticMechanism" for item in projection.objects) == 61
    assert sum(item.object_type == "BenchmarkValidation" for item in projection.objects) == 427
    rejected = next(
        item
        for item in projection.objects
        if item.id == "diagnostic-mechanism:kubernetes_webhook_fail_open_recovery_seed"
    )
    assert rejected.properties["status"] == "rejected"
    assert rejected.properties["operationalized"] is False


async def test_projects_merged_runtime_catalog_idempotently_to_typed_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = load_ontology_catalog(
        _ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=_ROOT / "rule-catalog/probes",
    )
    store = _SyncRequiredOntologyStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    rule = Rule.model_validate(
        yaml.safe_load(
            (_ROOT / "rule-catalog/catalog/kubernetes-node-pool.multi-zone.yaml").read_text(
                encoding="utf-8"
            )
        )
    )
    release = catalog.build_release()
    control_loop = SimpleNamespace(
        ontology_instance_store=store,
        rules=(rule,),
        action_types=catalog.action_types,
        property_semantics=catalog.property_semantics,
        ontology_release=release,
    )
    monkeypatch.setattr("fdai.runtime.catalog_ontology.shutil.which", lambda _name: "/opa")
    original_read_text = Path.read_text

    def reject_property_registry_reread(path: Path, *args: object, **kwargs: object) -> str:
        if path.name == "property-semantics.yaml":
            raise AssertionError("runtime projection MUST use the already-loaded registry")
        return original_read_text(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", reject_property_registry_reread)

    first = await project_catalog_ontology(control_loop)  # type: ignore[arg-type]
    second = await project_catalog_ontology(control_loop)  # type: ignore[arg-type]

    assert first == second
    graph = await store.query_objects(
        object_types=("DiagnosticMechanism", "BenchmarkValidation"),
        limit=500,
    )
    assert len(graph.objects) == 488
    assert len(graph.links) == 427
    assert all(item.revision == 1 for item in graph.objects)
    binding_id = "rule-objective-binding:binding.node-pool-zone-resilience@1.0.0"
    objective_id = "control-objective:reliability.node-pool.zone-failure-tolerance@1.0.0"
    binding = await store.get_object(binding_id)
    assert binding is not None
    assert binding.revision == 1
    assert binding.properties["state"] == "candidate"
    assert binding.type_ref == store._release.type_ref(
        OntologyDeclarationKind.OBJECT, "RuleObjectiveBinding"
    )
    assert (
        binding.type_ref.version
        == release.type_ref(OntologyDeclarationKind.OBJECT, "RuleObjectiveBinding").version
    )
    assert not (
        set(binding.properties)
        & {"approval", "execution_authority", "promotion", "policy_verdict", "risk_decision"}
    )
    objective = await store.get_object(objective_id)
    assert objective is not None
    assert objective.type_ref == store._release.type_ref(
        OntologyDeclarationKind.OBJECT, "ControlObjective"
    )
    relations = await store.query_objects(
        object_types=("RuleObjectiveBinding", "ControlObjective", "Rule"),
        limit=10,
    )
    assert {(item.from_id, item.link_type, item.to_id) for item in relations.links} >= {
        (objective_id, "objective_bound_by", binding_id),
        (binding_id, "binding_targets_rule", rule.id),
    }
    assert all(item.type_ref is not None for item in relations.links)
    assert store.catalog_synced is True


def test_bootstrap_syncs_the_release_history_before_reading_persisted_incidents() -> None:
    """A persisted object pins an earlier release, so the read MUST follow the sync."""
    source = (_ROOT / "services/core-control-plane/src/fdai/runtime/bootstrap_core.py").read_text(
        encoding="utf-8"
    )

    sync_at = source.index("await sync_ontology_catalog(")
    read_at = source.index("await incident_runtime.bind_projection(")

    assert sync_at < read_at


async def test_catalog_refresh_preserves_prior_immutable_validation_receipts() -> None:
    catalog = load_ontology_catalog(
        _ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=_ROOT / "rule-catalog/probes",
    )
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    payload = json.loads(
        (_ROOT / "docs/internals/sregym-absorption-ledger.json").read_text(encoding="utf-8")
    )
    first_ledger = validate_diagnostic_ledger(payload)
    changed = copy.deepcopy(payload)
    replacement_revision = next(
        revision
        for group in changed["groups"]
        for revision in group["commits"]
        if revision not in changed["absorbed_mechanisms"][0]["source_commits"]
    )
    changed["absorbed_mechanisms"][0]["source_commits"] = [replacement_revision]
    second_ledger = validate_diagnostic_ledger(changed)
    projector = CatalogOntologyProjector(store)

    await projector.replace(
        build_diagnostic_catalog_projection(first_ledger.mechanisms, benchmark_id="sregym")
    )
    await projector.replace(
        build_diagnostic_catalog_projection(second_ledger.mechanisms, benchmark_id="sregym")
    )

    graph = await store.query_objects(
        object_types=("DiagnosticMechanism", "BenchmarkValidation"),
        limit=500,
    )
    receipts = [item for item in graph.objects if item.object_type == "BenchmarkValidation"]
    assert len(receipts) == 434
    assert len(graph.links) == 434
    assert all(item.revision == 1 for item in receipts)


async def test_equivalence_receipt_survives_catalog_refresh_and_rejects_rewrite() -> None:
    catalog = load_ontology_catalog(
        _ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=_ROOT / "rule-catalog/probes",
    )
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types, link_types=catalog.link_types
    )
    projector = CatalogOntologyProjector(
        store, owned_object_types=("EquivalenceValidationReceipt",)
    )
    receipt = OntologyObjectRecord(
        id="equivalence-validation-receipt:example@1.0.0",
        object_type="EquivalenceValidationReceipt",
        properties={
            "id": "equivalence-validation-receipt:example@1.0.0",
            "version": "1.0.0",
            "result": "validated",
            "reviewer": "Heimdall",
            "state": "reviewed",
            "content_digest": f"sha256:{'a' * 64}",
        },
    )
    await projector.replace(CatalogOntologyProjection(objects=(receipt,), links=()))
    await projector.replace(CatalogOntologyProjection(objects=(), links=()))
    retained = await store.get_object(receipt.id)
    assert retained is not None and retained.revision == 1
    with pytest.raises(ValueError, match="immutable catalog receipt content changed"):
        await projector.replace(
            CatalogOntologyProjection(
                objects=(
                    OntologyObjectRecord(
                        id=receipt.id,
                        object_type=receipt.object_type,
                        properties={**receipt.properties, "result": "rejected"},
                    ),
                ),
                links=(),
            )
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (("source_commit_count", 123), ("absorbed_mechanism_count", 60)),
)
def test_rejects_incomplete_diagnostic_ledger(tmp_path: Path, field: str, value: int) -> None:
    source = json.loads(
        (_ROOT / "docs/internals/sregym-absorption-ledger.json").read_text(encoding="utf-8")
    )
    source[field] = value
    path = tmp_path / "docs/internals"
    path.mkdir(parents=True)
    (path / "sregym-absorption-ledger.json").write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(RuntimeError, match="completeness"):
        load_diagnostic_catalog_projection(tmp_path)
