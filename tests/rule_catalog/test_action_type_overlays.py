"""Overlay-loader tests for the ActionType catalog (F5 groundwork).

Covers the file-based overlay layer in
[action-ontology.md § 7.1](../../../../docs/roadmap/action-ontology.md).
The Rego and runtime override layers land in a later wave.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from aiopspilot.rule_catalog.schema.action_type import (
    ActionTypeCatalogError,
    load_action_type_catalog,
)
from aiopspilot.shared.contracts.registry import PackageResourceSchemaRegistry


def _write_yaml(path: Path, data: dict) -> None:
    with path.open("w") as f:
        yaml.dump(data, f, sort_keys=False)


def _minimal_upstream(name: str = "remediate.example") -> dict:
    return {
        "schema_version": "1.0.0",
        "name": name,
        "version": "1.0.0",
        "operation": "tag",
        "interfaces": ["ControlPlane", "IdempotentByKey"],
        "rollback_contract": "pr_revert",
        "irreversible": False,
        "default_mode": "shadow",
        "promotion_gate": {
            "min_shadow_days": 7,
            "min_samples": 50,
            "min_accuracy": 0.99,
            "max_policy_escapes": 0,
        },
        "preconditions": [],
        "stop_conditions": [{"kind": "time_box_exceeded_seconds", "seconds": 60}],
        "blast_radius": {"computation": "static_enum", "static_bucket": "resource"},
        "description": "test action type",
        "category": "remediation",
        "trigger_kind": {"kind": "rule_violation"},
        "execution_path": "pr_native",
        "ceiling_by_tier": {
            "t0": {"max_autonomy": "enforce_auto", "min_role": "contributor"},
            "t1": {"max_autonomy": "shadow_only", "min_role": "contributor"},
            "t2": {"max_autonomy": "shadow_only", "min_role": "approver"},
        },
    }


def test_overlay_missing_root_is_noop(tmp_path):
    (tmp_path / "upstream").mkdir()
    _write_yaml(tmp_path / "upstream" / "remediate.example.yaml", _minimal_upstream())
    # overlay_root does not exist -> passes through untouched
    catalog = load_action_type_catalog(
        tmp_path / "upstream",
        schema_registry=PackageResourceSchemaRegistry(),
        overlay_root=tmp_path / "overrides",  # missing dir
    )
    assert len(catalog) == 1
    assert catalog[0].name == "remediate.example"


def test_overlay_downgrades_t0_autonomy(tmp_path):
    upstream = tmp_path / "upstream"
    overrides = tmp_path / "overrides"
    upstream.mkdir()
    overrides.mkdir()
    _write_yaml(upstream / "remediate.example.yaml", _minimal_upstream())
    _write_yaml(
        overrides / "remediate.example.yaml",
        {
            "name": "remediate.example",
            "ceiling_by_tier": {
                "t0": {"max_autonomy": "enforce_hil"},
            },
        },
    )
    catalog = load_action_type_catalog(
        upstream,
        schema_registry=PackageResourceSchemaRegistry(),
        overlay_root=overrides,
    )
    assert len(catalog) == 1
    entry = catalog[0]
    # Overlay wins on t0.max_autonomy
    assert entry.ceiling_by_tier.t0.max_autonomy.value == "enforce_hil"
    # Overlay was silent on t0.min_role -> upstream stays
    assert entry.ceiling_by_tier.t0.min_role.value == "contributor"


def test_overlay_orphan_name_rejected(tmp_path):
    upstream = tmp_path / "upstream"
    overrides = tmp_path / "overrides"
    upstream.mkdir()
    overrides.mkdir()
    _write_yaml(upstream / "remediate.example.yaml", _minimal_upstream())
    _write_yaml(
        overrides / "typo.yaml",
        {"name": "remediate.exmaple", "irreversible": True},  # typo!
    )
    with pytest.raises(ActionTypeCatalogError) as exc_info:
        load_action_type_catalog(
            upstream,
            schema_registry=PackageResourceSchemaRegistry(),
            overlay_root=overrides,
        )
    assert "does not exist in upstream" in str(exc_info.value)


def test_overlay_replaces_lists_wholesale(tmp_path):
    """Lists are replaced, not concatenated (preconditions/stop_conditions)."""

    upstream = tmp_path / "upstream"
    overrides = tmp_path / "overrides"
    upstream.mkdir()
    overrides.mkdir()
    base = _minimal_upstream()
    base["stop_conditions"] = [
        {"kind": "time_box_exceeded_seconds", "seconds": 60},
        {"kind": "provider_api_error_streak", "count": 5},
    ]
    _write_yaml(upstream / "remediate.example.yaml", base)
    _write_yaml(
        overrides / "remediate.example.yaml",
        {
            "name": "remediate.example",
            "stop_conditions": [
                {"kind": "time_box_exceeded_seconds", "seconds": 30},
            ],
        },
    )
    catalog = load_action_type_catalog(
        upstream,
        schema_registry=PackageResourceSchemaRegistry(),
        overlay_root=overrides,
    )
    assert len(catalog[0].stop_conditions) == 1


def test_overlay_duplicate_name_rejected(tmp_path):
    upstream = tmp_path / "upstream"
    overrides = tmp_path / "overrides"
    upstream.mkdir()
    overrides.mkdir()
    _write_yaml(upstream / "remediate.example.yaml", _minimal_upstream())
    _write_yaml(
        overrides / "a.yaml",
        {"name": "remediate.example", "irreversible": True},
    )
    _write_yaml(
        overrides / "b.yaml",
        {"name": "remediate.example", "irreversible": False},
    )
    with pytest.raises(ActionTypeCatalogError) as exc_info:
        load_action_type_catalog(
            upstream,
            schema_registry=PackageResourceSchemaRegistry(),
            overlay_root=overrides,
        )
    assert "duplicate overlay name" in str(exc_info.value)


def test_overlay_missing_name_rejected(tmp_path):
    upstream = tmp_path / "upstream"
    overrides = tmp_path / "overrides"
    upstream.mkdir()
    overrides.mkdir()
    _write_yaml(upstream / "remediate.example.yaml", _minimal_upstream())
    _write_yaml(overrides / "nameless.yaml", {"irreversible": True})
    with pytest.raises(ActionTypeCatalogError) as exc_info:
        load_action_type_catalog(
            upstream,
            schema_registry=PackageResourceSchemaRegistry(),
            overlay_root=overrides,
        )
    assert "MUST declare 'name'" in str(exc_info.value)
