"""Configuration and measurement baseline contracts, loaders, and stores."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from fdai.rule_catalog.schema.baseline_catalog import (
    BaselineCatalogError,
    load_configuration_baseline_catalog,
    load_configuration_baseline_from_mapping,
    load_measurement_baseline_catalog,
    load_measurement_baseline_from_mapping,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
BASELINES_ROOT = REPO_ROOT / "rule-catalog" / "baselines"


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


def test_shipped_repository_stores_load(tmp_path: Path) -> None:
    del tmp_path
    assert load_configuration_baseline_catalog(BASELINES_ROOT / "configuration") == ()
    assert load_measurement_baseline_catalog(BASELINES_ROOT / "measurement") == ()
