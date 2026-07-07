"""Probe catalog loader tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from aiopspilot.rule_catalog.schema.probe import (
    ProbeCatalogError,
    load_probe_catalog,
    probe_ids,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROBES_ROOT = _REPO_ROOT / "rule-catalog" / "probes"


def test_shipped_probes_load():
    catalog = load_probe_catalog(_PROBES_ROOT)
    ids = probe_ids(catalog)
    assert {"vm_traffic_last_5m", "storage_access_log", "lb_backend_health"} <= ids


def test_probe_manifest_fields():
    catalog = load_probe_catalog(_PROBES_ROOT)
    vm = next(p for p in catalog if p.id == "vm_traffic_last_5m")
    assert vm.adapter_ref == "probe-adapters/azure-monitor"
    assert vm.timeout_seconds == 5
    assert vm.cache_ttl_seconds == 60
    assert set(vm.interpretation) == {"quiet", "active", "overloaded"}


def test_invalid_probe_raises(tmp_path):
    # Copy the schema so the loader can validate.
    schema_src = _PROBES_ROOT / "probe.schema.json"
    schema_dst = tmp_path / "probe.schema.json"
    schema_dst.write_bytes(schema_src.read_bytes())
    (tmp_path / "bad.yaml").write_text("id: x\n")  # missing required fields
    with pytest.raises(ProbeCatalogError) as exc_info:
        load_probe_catalog(tmp_path)
    # bad.yaml has multiple validation errors; message aggregates them
    assert "bad.yaml" in str(exc_info.value)


def test_missing_root_raises(tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(FileNotFoundError):
        load_probe_catalog(missing)


def test_placeholder_mode_returns_empty(tmp_path):
    """A probe root with no schema file returns an empty tuple.

    This matches the Day-1 contract: rule-catalog/probes/ can exist
    with only README.md before Month 1 lands the schema, and startup
    MUST NOT crash.
    """

    (tmp_path / "README.md").write_text("placeholder\n")
    catalog = load_probe_catalog(tmp_path)
    assert catalog == ()


def test_duplicate_id_rejected(tmp_path):
    schema_src = _PROBES_ROOT / "probe.schema.json"
    (tmp_path / "probe.schema.json").write_bytes(schema_src.read_bytes())
    body = (
        'schema_version: "1.0.0"\n'
        "id: dup_probe\n"
        'description: "test"\n'
        "adapter_ref: probe-adapters/fake\n"
        "interpretation:\n"
        '  quiet: "x < 1"\n'
        '  active: "x < 2"\n'
        '  overloaded: "x >= 2"\n'
        "timeout_seconds: 5\n"
        "cache_ttl_seconds: 60\n"
    )
    (tmp_path / "a.yaml").write_text(body)
    (tmp_path / "b.yaml").write_text(body)
    with pytest.raises(ProbeCatalogError) as exc_info:
        load_probe_catalog(tmp_path)
    assert "duplicate probe id" in str(exc_info.value)
