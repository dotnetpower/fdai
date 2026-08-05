"""Tests for runtime diagnostic catalog projection composition."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai.core.ontology_platform import CatalogOntologyProjector
from fdai.core.ontology_platform.diagnostic_ledger import validate_diagnostic_ledger
from fdai.core.ontology_platform.diagnostic_projection import (
    build_diagnostic_catalog_projection,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.runtime.catalog_ontology import (
    load_diagnostic_catalog_projection,
    project_catalog_ontology,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

_ROOT = Path(__file__).resolve().parents[2]


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
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    control_loop = SimpleNamespace(
        ontology_instance_store=store,
        rules=(),
        action_types=(),
    )
    monkeypatch.setattr("fdai.runtime.catalog_ontology.shutil.which", lambda _name: "/opa")

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
