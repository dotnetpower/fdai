from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.rule_catalog.schema.framework_catalog import load_framework_catalog
from fdai.rule_catalog.schema.wara_assessment import (
    QuerySafetyClassification,
    ResourceTypeDisposition,
    canonical_digest,
    classify_wara_query,
    load_wara_assessment_catalog,
)
from fdai.rule_catalog.schema.wara_evaluator_binding import (
    WaraEvaluatorSemantics,
    load_wara_evaluator_bindings,
)

ROOT = Path(__file__).resolve().parents[4]
CATALOG = ROOT / "rule-catalog"
CROSSWALK = CATALOG / "collected/wara-aprl/assessment/crosswalk.json"
QUERIES = CATALOG / "collected/wara-aprl/assessment/queries.json"
EVALUATOR_BINDINGS = CATALOG / "collected/wara-aprl/assessment/evaluator-bindings.json"


def _load():
    framework = load_framework_catalog(
        CATALOG / "collected/wara-aprl",
        best_practices=(),
        objective_refs=frozenset(),
    )[0]
    return load_wara_assessment_catalog(
        CROSSWALK,
        QUERIES,
        framework=framework,
        framework_path=CATALOG / "collected/wara-aprl/azure-wara.json",
    )


def test_crosswalk_exactly_accounts_for_pinned_wara_inventory() -> None:
    catalog, queries = _load()

    assert len(catalog.recommendations) == 393
    assert len(catalog.resource_type_mappings) == 80
    assert len(queries.queries) == 143
    assert sum(item.automation_available for item in catalog.recommendations) == 143
    assert sum(item.manual_evidence is not None for item in catalog.recommendations) == 250
    assert all(
        item.query_review is not None
        for item in catalog.recommendations
        if item.automation_available
    )
    assert all(
        item.manual_evidence is not None
        for item in catalog.recommendations
        if not item.automation_available
    )
    assert len(catalog.umbrella_relations) == 13
    assert all(not item.semantic_equivalence for item in catalog.umbrella_relations)


def test_exact_evaluator_overlay_is_pinned_to_generated_catalog() -> None:
    catalog, queries = _load()
    overlay = load_wara_evaluator_bindings(
        EVALUATOR_BINDINGS,
        catalog=catalog,
        queries=queries,
    )

    assert len(overlay.bindings) == 3
    assert all(
        binding.semantics is WaraEvaluatorSemantics.MATCHING_ROWS_FAILED
        for binding in overlay.bindings
    )
    records = {record.aprl_guid: record for record in catalog.recommendations}
    for binding in overlay.bindings:
        review = records[binding.aprl_guid].query_review
        assert review is not None
        assert review.body_digest == binding.query_digest
        assert review.blocked_reasons == ("missing_exact_evaluator",)


def test_exact_evaluator_overlay_digest_drift_fails_closed(tmp_path: Path) -> None:
    catalog, queries = _load()
    raw = json.loads(EVALUATOR_BINDINGS.read_text(encoding="utf-8"))
    raw["bindings"][0]["query_digest"] = "sha256:" + "0" * 64
    tampered = tmp_path / "evaluator-bindings.json"
    tampered.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="overlay digest mismatch"):
        load_wara_evaluator_bindings(tampered, catalog=catalog, queries=queries)


def test_exact_evaluator_overlay_query_drift_fails_closed(tmp_path: Path) -> None:
    catalog, queries = _load()
    raw = json.loads(EVALUATOR_BINDINGS.read_text(encoding="utf-8"))
    raw["bindings"][0]["query_digest"] = "sha256:" + "0" * 64
    raw["overlay_digest"] = canonical_digest(
        {key: value for key, value in raw.items() if key != "overlay_digest"}
    )
    tampered = tmp_path / "evaluator-bindings.json"
    tampered.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="query digest mismatch"):
        load_wara_evaluator_bindings(tampered, catalog=catalog, queries=queries)


def test_resource_types_are_reviewed_without_broadening_ambiguous_identity() -> None:
    catalog, _ = _load()
    mappings = {item.normalized_provider_type: item for item in catalog.resource_type_mappings}

    assert mappings["microsoft.compute/virtualmachines"].canonical_resource_type == "compute.vm"
    assert mappings["microsoft.web/sites"].disposition is ResourceTypeDisposition.AMBIGUOUS
    assert mappings["microsoft.sql/servers/databases"].requires_exact_child_scope is True
    assert (
        mappings["microsoft.sql/servers/databases"].parent_provider_type == "microsoft.sql/servers"
    )


def test_query_safety_is_bounded_and_rejects_control_or_join_syntax() -> None:
    classification, reasons, tables, resource_types = classify_wara_query(
        "resources | where type == 'microsoft.compute/virtualmachines'",
        declared_provider_type="microsoft.compute/virtualmachines",
    )
    assert classification is QuerySafetyClassification.READ_ONLY_BOUNDED
    assert reasons == ()
    assert tables == ("resources",)
    assert resource_types == ("microsoft.compute/virtualmachines",)

    classification, reasons, _, _ = classify_wara_query(
        "resources | join kind=inner (resourcecontainers) on subscriptionId",
        declared_provider_type="microsoft.compute/virtualmachines",
    )
    assert classification is QuerySafetyClassification.BLOCKED
    assert "unsupported_join" in reasons

    classification, reasons, _, _ = classify_wara_query(
        "set query_results_cache_max_age = time(1h)"
    )
    assert classification is QuerySafetyClassification.BLOCKED
    assert "control_command" in reasons

    classification, reasons, _, _ = classify_wara_query(
        "resources | where type == 'microsoft.storage/storageaccounts'",
        declared_provider_type="microsoft.compute/virtualmachines",
    )
    assert classification is QuerySafetyClassification.BLOCKED
    assert "undeclared_resource_type" in reasons


def test_crosswalk_digest_tampering_fails_closed(tmp_path: Path) -> None:
    raw = json.loads(CROSSWALK.read_text(encoding="utf-8"))
    raw["expected_counts"]["active_recommendations"] = 392
    raw["crosswalk_digest"] = canonical_digest(
        {key: value for key, value in raw.items() if key != "crosswalk_digest"}
    )
    tampered = tmp_path / "crosswalk.json"
    tampered.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="partition|count"):
        load_wara_assessment_catalog(tampered, QUERIES)
