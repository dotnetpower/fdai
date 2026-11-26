"""Configuration and measurement baseline contracts, loaders, and stores."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from fdai.rule_catalog.schema.baseline_catalog import (
    BaselineCatalogError,
    ConfigurationBaselineControlSetReport,
    evaluate_configuration_baseline_control_set,
    load_configuration_baseline_catalog,
    load_configuration_baseline_from_mapping,
    load_measurement_baseline_catalog,
    load_measurement_baseline_from_mapping,
    require_resolved_configuration_baseline_control_set,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
BASELINES_ROOT = REPO_ROOT / "rule-catalog" / "baselines"
CATALOG_DIRS = (REPO_ROOT / "rule-catalog" / "catalog", REPO_ROOT / "rule-catalog" / "collected")


def _configuration_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "kind": "config-baseline",
        "id": "kubernetes-cluster.hardening.baseline",
        "version": "3.1.0",
        "source": "example-baseline",
        "resource_type": "kubernetes-cluster",
        "controls": [
            "kubernetes-cluster.rbac.enabled",
            "kubernetes-cluster.audit-log.enabled",
        ],
        "provenance": {
            "source_url": "https://example.com/baseline/kubernetes",
            "source_version": "v3.1.0",
            "resolved_ref": "0" * 40,
            "content_hash": "sha256:" + "0" * 64,
            "license": "Apache-2.0",
            "retrieved_at": "2026-07-03T00:00:00Z",
            "mapped_by": "catalog-team",
        },
    }
    document.update(overrides)
    return document


def _measurement_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "kind": "measurement-baseline",
        "id": "baseline.reference-agent.2026-07",
        "scenario_set": "v2026.07",
        "reference_agent": "reference-agent@1.0.0",
        "window": "P30D",
        "metrics": {
            "cost_per_incident_usd": 0.0,
            "auto_resolution_rate": 0.0,
            "mttr_seconds": 0,
        },
        "sample_size": 0,
        "provenance": {
            "measured_at": "2026-07-03T00:00:00Z",
            "measured_by": "phase-0",
        },
    }
    document.update(overrides)
    return document


def _write(root: Path, name: str, document: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(yaml.safe_dump(document, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# Configuration baseline
# ---------------------------------------------------------------------------


def test_configuration_baseline_materializes_the_documented_shape() -> None:
    baseline = load_configuration_baseline_from_mapping(_configuration_document())

    assert baseline.id == "kubernetes-cluster.hardening.baseline"
    assert baseline.resource_type == "kubernetes-cluster"
    assert baseline.controls == (
        "kubernetes-cluster.rbac.enabled",
        "kubernetes-cluster.audit-log.enabled",
    )
    assert baseline.provenance.license == "Apache-2.0"
    assert baseline.provenance.retrieved_at == datetime(2026, 7, 3, tzinfo=UTC)


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "rule"},
        {"controls": []},
        {"controls": ["dup", "dup"]},
        {"id": "Bad-Id"},
        {"version": "3.1"},
        {"unexpected": True},
    ],
)
def test_configuration_baseline_rejects_invalid_documents(overrides: dict[str, Any]) -> None:
    with pytest.raises(BaselineCatalogError):
        load_configuration_baseline_from_mapping(_configuration_document(**overrides))


def test_configuration_baseline_rejects_a_naive_timestamp() -> None:
    document = _configuration_document()
    document["provenance"]["retrieved_at"] = "2026-07-03T00:00:00"
    with pytest.raises(BaselineCatalogError):
        load_configuration_baseline_from_mapping(document)


# ---------------------------------------------------------------------------
# Measurement baseline
# ---------------------------------------------------------------------------


def test_measurement_baseline_materializes_the_documented_shape() -> None:
    baseline = load_measurement_baseline_from_mapping(_measurement_document())

    assert baseline.id == "baseline.reference-agent.2026-07"
    assert baseline.window == "P30D"
    assert baseline.metrics["mttr_seconds"] == 0.0
    assert baseline.sample_size == 0
    assert baseline.provenance.measured_by == "phase-0"


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "reference-agent.2026-07"},
        {"kind": "config-baseline"},
        {"metrics": {}},
        {"metrics": {"Bad Metric": 1}},
        {"sample_size": -1},
        {"window": "30D"},
    ],
)
def test_measurement_baseline_rejects_invalid_documents(overrides: dict[str, Any]) -> None:
    with pytest.raises(BaselineCatalogError):
        load_measurement_baseline_from_mapping(_measurement_document(**overrides))


def test_measurement_baseline_id_namespace_cannot_collide_with_a_rule_id() -> None:
    with pytest.raises(BaselineCatalogError):
        load_measurement_baseline_from_mapping(
            _measurement_document(id="azure-builtin.storage.secure-transfer")
        )


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------


def test_stores_load_in_id_order(tmp_path: Path) -> None:
    _write(tmp_path, "b.yaml", _configuration_document(id="zzz.baseline"))
    _write(tmp_path, "a.yaml", _configuration_document(id="aaa.baseline"))

    loaded = load_configuration_baseline_catalog(tmp_path)

    assert [item.id for item in loaded] == ["aaa.baseline", "zzz.baseline"]


def test_store_rejects_duplicate_ids(tmp_path: Path) -> None:
    _write(tmp_path, "a.yaml", _configuration_document())
    _write(tmp_path, "b.yaml", _configuration_document())

    with pytest.raises(BaselineCatalogError, match="duplicate baseline id"):
        load_configuration_baseline_catalog(tmp_path)


def test_one_invalid_document_fails_the_whole_store(tmp_path: Path) -> None:
    _write(tmp_path, "good.yaml", _configuration_document())
    _write(tmp_path, "bad.yaml", _configuration_document(id="Bad-Id"))

    with pytest.raises(BaselineCatalogError):
        load_configuration_baseline_catalog(tmp_path)


def test_missing_store_loads_as_empty(tmp_path: Path) -> None:
    assert load_configuration_baseline_catalog(tmp_path / "absent") == ()
    assert load_measurement_baseline_catalog(tmp_path / "absent") == ()


def test_hidden_paths_are_skipped(tmp_path: Path) -> None:
    _write(tmp_path / ".drafts", "a.yaml", _configuration_document(id="Bad-Id"))

    assert load_configuration_baseline_catalog(tmp_path) == ()


def test_shipped_measurement_store_loads_as_empty(tmp_path: Path) -> None:
    del tmp_path
    assert load_measurement_baseline_catalog(BASELINES_ROOT / "measurement") == ()


def test_shipped_configuration_store_loads_the_reviewed_baseline(tmp_path: Path) -> None:
    del tmp_path
    loaded = load_configuration_baseline_catalog(BASELINES_ROOT / "configuration")

    assert [item.id for item in loaded] == ["kubernetes-cluster.hardening.baseline"]
    (baseline,) = loaded
    assert baseline.resource_type == "kubernetes-cluster"
    assert baseline.provenance.license == "LicenseRef-reference-only"


# ---------------------------------------------------------------------------
# Control-set resolution - the T0 consumer for a catalog ConfigurationBaseline
# ---------------------------------------------------------------------------


def test_evaluate_configuration_baseline_control_set_splits_resolved_and_unresolved() -> None:
    baseline = load_configuration_baseline_from_mapping(
        _configuration_document(
            controls=["known.rule", "also-known.rule", "missing.rule"],
        )
    )

    report = evaluate_configuration_baseline_control_set(
        baseline, known_rule_ids={"known.rule", "also-known.rule"}
    )

    assert isinstance(report, ConfigurationBaselineControlSetReport)
    assert report.baseline_id == baseline.id
    assert report.resource_type == baseline.resource_type
    assert report.resolved_controls == ("also-known.rule", "known.rule")
    assert report.unresolved_controls == ("missing.rule",)
    assert report.is_resolved is False


def test_evaluate_configuration_baseline_control_set_fully_resolved() -> None:
    baseline = load_configuration_baseline_from_mapping(
        _configuration_document(controls=["known.rule"])
    )

    report = evaluate_configuration_baseline_control_set(baseline, known_rule_ids={"known.rule"})

    assert report.unresolved_controls == ()
    assert report.is_resolved is True


def test_require_resolved_configuration_baseline_control_set_raises_on_unresolved() -> None:
    baseline = load_configuration_baseline_from_mapping(
        _configuration_document(controls=["missing.rule"])
    )

    with pytest.raises(BaselineCatalogError, match="does not resolve to a known Rule id"):
        require_resolved_configuration_baseline_control_set(baseline, known_rule_ids=set())


def test_require_resolved_configuration_baseline_control_set_passes_when_fully_resolved() -> None:
    baseline = load_configuration_baseline_from_mapping(
        _configuration_document(controls=["known.rule"])
    )

    report = require_resolved_configuration_baseline_control_set(
        baseline, known_rule_ids={"known.rule"}
    )

    assert report.is_resolved is True


def test_shipped_configuration_baseline_resolves_against_the_real_rule_catalog() -> None:
    """Focused loaded-baseline evaluation: the shipped, reviewed baseline's
    controls MUST all resolve against ids actually present in the shipped
    Rule catalog - the deterministic T0 binding this ledger item requires."""

    (baseline,) = load_configuration_baseline_catalog(BASELINES_ROOT / "configuration")
    known_rule_ids = {
        str(document["id"])
        for root in CATALOG_DIRS
        if root.is_dir()
        for path in root.rglob("*.yaml")
        for document in [yaml.safe_load(path.read_text(encoding="utf-8"))]
        if isinstance(document, dict) and "id" in document
    }

    report = require_resolved_configuration_baseline_control_set(
        baseline, known_rule_ids=known_rule_ids
    )

    assert report.resolved_controls == tuple(sorted(baseline.controls))
    assert report.unresolved_controls == ()
