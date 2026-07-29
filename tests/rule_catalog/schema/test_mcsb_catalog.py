"""Versioned MCSB control and implementation-crosswalk loader tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fdai.rule_catalog.schema.mcsb_catalog import McsbCatalogError, load_mcsb_catalogs


def _controls() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "kind": "mcsb-controls",
        "benchmark": "mcsb",
        "benchmark_version": "v1",
        "status": "stable",
        "control_import_status": "complete",
        "title": "Microsoft Cloud Security Benchmark v1",
        "source": {
            "source_url": "https://learn.microsoft.com/security/benchmark/azure/overview-mcsb-v1",
            "artifact_url": "https://example.com/mcsb.xlsx",
            "resolved_ref": "example-revision",
            "content_hash": "sha256:" + "0" * 64,
            "license": "CC-BY-4.0",
            "redistribution": "embeddable",
            "retrieved_at": "2026-07-29T00:00:00Z",
        },
        "controls": [
            {"id": "NS-1", "domain": "NS", "title": "Establish segmentation"},
            {"id": "IR-1", "domain": "IR", "title": "Prepare incident response"},
        ],
    }


def _crosswalk() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "kind": "mcsb-crosswalk",
        "benchmark": "mcsb",
        "benchmark_version": "v1",
        "policy_profiles": [{"profile_id": "mcsb-v1", "policy_ref_count": 2}],
        "mappings": [
            {
                "control_id": "NS-1",
                "coverage": "partial",
                "rule_ids": ["network.rule"],
                "runtime_observation_ids": ["network-observation"],
                "manual_evidence_refs": [],
            },
            {
                "control_id": "IR-1",
                "coverage": "manual",
                "rule_ids": [],
                "runtime_observation_ids": [],
                "manual_evidence_refs": ["incident-response-plan"],
            },
        ],
    }


def _write(root: Path, controls: dict[str, object], crosswalk: dict[str, object]) -> None:
    version = root / "v1"
    version.mkdir()
    (version / "controls.yaml").write_text(yaml.safe_dump(controls, sort_keys=False))
    (version / "crosswalk.yaml").write_text(yaml.safe_dump(crosswalk, sort_keys=False))


def _load(root: Path):
    return load_mcsb_catalogs(
        root,
        known_rule_ids={"network.rule"},
        known_policy_profiles={"mcsb-v1": 2},
        known_runtime_observation_ids={"network-observation"},
        known_manual_evidence_refs={"incident-response-plan"},
    )


def test_loads_versioned_controls_and_crosswalk(tmp_path: Path) -> None:
    _write(tmp_path, _controls(), _crosswalk())

    (catalog,) = _load(tmp_path)

    assert catalog.benchmark_version == "v1"
    assert [control.id for control in catalog.controls] == ["NS-1", "IR-1"]
    assert catalog.coverage_counts() == {"manual": 1, "partial": 1}


def test_missing_crosswalk_entry_defaults_to_unmapped(tmp_path: Path) -> None:
    crosswalk = _crosswalk()
    crosswalk["mappings"] = crosswalk["mappings"][:1]  # type: ignore[index]
    _write(tmp_path, _controls(), crosswalk)

    (catalog,) = _load(tmp_path)

    assert catalog.coverage_counts() == {"partial": 1, "unmapped": 1}


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("duplicate", "control ids MUST be unique"),
        ("domain", "does not match id prefix"),
        ("rule", "unknown rule"),
        ("profile", "does not match catalog"),
        ("coverage", "automated coverage needs"),
    ],
)
def test_rejects_invalid_identity_reference_and_coverage(
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    controls = _controls()
    crosswalk = _crosswalk()
    control_rows = controls["controls"]
    mapping_rows = crosswalk["mappings"]
    profile_rows = crosswalk["policy_profiles"]
    assert isinstance(control_rows, list)
    assert isinstance(mapping_rows, list)
    assert isinstance(profile_rows, list)
    if case == "duplicate":
        control_rows.append({"id": "NS-1", "domain": "NS", "title": "Duplicate"})
    elif case == "domain":
        control_rows[0]["domain"] = "IM"
    elif case == "rule":
        mapping_rows[0]["rule_ids"].append("missing.rule")
    elif case == "profile":
        profile_rows[0]["policy_ref_count"] = 3
    else:
        mapping_rows[1]["coverage"] = "automated"
    _write(tmp_path, controls, crosswalk)

    with pytest.raises(McsbCatalogError, match=message):
        _load(tmp_path)
