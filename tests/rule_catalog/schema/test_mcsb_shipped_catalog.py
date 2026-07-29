"""Completeness gates for the shipped versioned MCSB catalogs."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from fdai.delivery.azure.security_posture_mcsb import MCSB_CONTROLS_BY_OBSERVATION
from fdai.rule_catalog.schema.mcsb_catalog import McsbCoverage, load_mcsb_catalogs

_ROOT = Path(__file__).resolve().parents[3]
_CATALOG = _ROOT / "rule-catalog"


def _mapping(value: Any) -> Mapping[str, Any]:
    assert isinstance(value, Mapping)
    return value


def _yaml(path: Path) -> Mapping[str, Any]:
    return _mapping(yaml.safe_load(path.read_text(encoding="utf-8")))


def _rule_sources() -> dict[str, str]:
    return {
        str(raw["id"]): str(raw["source"])
        for path in sorted((_CATALOG / "catalog").glob("*.yaml"))
        if (raw := _yaml(path))
    }


def _policy_profiles() -> dict[str, int]:
    return {
        str(raw["id"]): len(raw.get("rules", ()))
        for path in sorted((_CATALOG / "profiles" / "collected").glob("*.yaml"))
        if (raw := _yaml(path))
    }


def _manual_evidence_refs() -> set[str]:
    raw = _yaml(_ROOT / "config" / "architecture-review.yaml")
    review = _mapping(raw["architecture_review"])
    gate = _mapping(review["production_gate"])
    artifacts = {str(_mapping(item)["id"]) for item in review["artifacts"]}
    return artifacts | {str(item) for item in gate["required_evidence"]}


def _catalogs():
    rule_sources = _rule_sources()
    return load_mcsb_catalogs(
        _CATALOG / "compliance" / "mcsb",
        known_rule_ids=set(rule_sources),
        known_policy_profiles=_policy_profiles(),
        known_runtime_observation_ids=set(MCSB_CONTROLS_BY_OBSERVATION),
        known_manual_evidence_refs=_manual_evidence_refs(),
    )


def test_v1_import_is_complete_and_version_pinned() -> None:
    catalogs = {catalog.benchmark_version: catalog for catalog in _catalogs()}
    v1 = catalogs["v1"]

    assert len(v1.controls) == 86
    assert Counter(control.domain for control in v1.controls) == {
        "NS": 10,
        "IM": 9,
        "PA": 8,
        "DP": 8,
        "AM": 5,
        "LT": 7,
        "IR": 7,
        "PV": 7,
        "ES": 3,
        "BR": 4,
        "DS": 7,
        "GS": 11,
    }
    assert v1.source.resolved_ref == "2e2db1189667b3108c91fe104661f6869fffd965"
    assert v1.source.content_hash == (
        "sha256:759bc9cddf82d5406a835e1fdcbbae2bc30d38d7c2205cafc599053f4dffeb8e"
    )


def test_v1_crosswalk_covers_every_curated_rule_without_overclaiming() -> None:
    catalogs = {catalog.benchmark_version: catalog for catalog in _catalogs()}
    v1 = catalogs["v1"]
    mapped_rules = {rule_id for mapping in v1.mappings for rule_id in mapping.rule_ids}
    mcsb_rules = {rule_id for rule_id, source in _rule_sources().items() if source == "mcsb"}

    assert mapped_rules == mcsb_rules
    assert len(mapped_rules) == 25
    assert v1.coverage_counts() == {"manual": 9, "partial": 16, "unmapped": 61}
    assert all(mapping.coverage is not McsbCoverage.AUTOMATED for mapping in v1.mappings)


def test_runtime_registry_and_crosswalk_are_bidirectionally_equal() -> None:
    v1 = next(catalog for catalog in _catalogs() if catalog.benchmark_version == "v1")
    observations_by_control: defaultdict[str, set[str]] = defaultdict(set)
    for mapping in v1.mappings:
        if mapping.runtime_observation_ids:
            observations_by_control[mapping.control_id].update(mapping.runtime_observation_ids)

    expected: defaultdict[str, set[str]] = defaultdict(set)
    for observation_id, control_ids in MCSB_CONTROLS_BY_OBSERVATION.items():
        for control_id in control_ids:
            expected[control_id.removeprefix("MCSB-")].add(observation_id)

    assert dict(observations_by_control) == dict(expected)


def test_v2_preview_stays_separate_and_metadata_only() -> None:
    catalogs = {catalog.benchmark_version: catalog for catalog in _catalogs()}
    v2 = catalogs["v2-preview"]

    assert v2.status == "preview"
    assert v2.control_import_status == "metadata_only"
    assert v2.controls == ()
    assert [(profile.profile_id, profile.policy_ref_count) for profile in v2.policy_profiles] == [
        ("compliance.security-center.preview-microsoft-cloud-security-benc", 410)
    ]
