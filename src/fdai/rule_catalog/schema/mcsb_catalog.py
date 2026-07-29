"""Strict versioned Microsoft Cloud Security Benchmark catalog loader."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Set
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_CONTROL_SCHEMA = "mcsb_controls.schema.json"
_CROSSWALK_SCHEMA = "mcsb_crosswalk.schema.json"


class McsbCoverage(StrEnum):
    AUTOMATED = "automated"
    PARTIAL = "partial"
    MANUAL = "manual"
    UNMAPPED = "unmapped"


@dataclass(frozen=True, slots=True)
class McsbCatalogIssue:
    key: str
    message: str


class McsbCatalogError(ValueError):
    """Aggregate schema, identity, and cross-reference failures."""

    def __init__(self, issues: list[McsbCatalogIssue]) -> None:
        self.issues = tuple(issues)
        preview = "; ".join(f"{issue.key}: {issue.message}" for issue in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"MCSB catalog load failed: {preview}{suffix}")


@dataclass(frozen=True, slots=True)
class McsbSource:
    source_url: str
    artifact_url: str | None
    resolved_ref: str
    content_hash: str
    license: str
    redistribution: str
    retrieved_at: str


@dataclass(frozen=True, slots=True)
class McsbControl:
    id: str
    domain: str
    title: str


@dataclass(frozen=True, slots=True)
class McsbControlMapping:
    control_id: str
    coverage: McsbCoverage
    rule_ids: tuple[str, ...] = ()
    runtime_observation_ids: tuple[str, ...] = ()
    manual_evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class McsbPolicyProfile:
    profile_id: str
    policy_ref_count: int


@dataclass(frozen=True, slots=True)
class McsbCatalog:
    benchmark_version: str
    status: str
    control_import_status: str
    title: str
    source: McsbSource
    controls: tuple[McsbControl, ...]
    mappings: tuple[McsbControlMapping, ...]
    policy_profiles: tuple[McsbPolicyProfile, ...]

    def coverage_counts(self) -> dict[str, int]:
        return dict(sorted(Counter(mapping.coverage.value for mapping in self.mappings).items()))


def _validator(schema_file: str) -> Draft202012Validator:
    schema = json.loads(
        resources.files(_SCHEMA_PACKAGE).joinpath(schema_file).read_text(encoding="utf-8")
    )
    return Draft202012Validator(schema, format_checker=FormatChecker())


_CONTROL_VALIDATOR = _validator(_CONTROL_SCHEMA)
_CROSSWALK_VALIDATOR = _validator(_CROSSWALK_SCHEMA)


def _load_yaml(
    path: Path,
    validator: Draft202012Validator,
) -> tuple[Mapping[str, Any] | None, list[McsbCatalogIssue]]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return None, [McsbCatalogIssue(path.as_posix(), str(exc))]
    if not isinstance(raw, Mapping):
        return None, [McsbCatalogIssue(path.as_posix(), "top-level value MUST be a mapping")]
    issues = [
        McsbCatalogIssue(
            f"{path.as_posix()}:{'/'.join(str(part) for part in error.path) or '<root>'}",
            error.message,
        )
        for error in sorted(validator.iter_errors(raw), key=lambda item: list(item.path))
    ]
    return raw, issues


def load_mcsb_catalogs(
    root: Path,
    *,
    known_rule_ids: Set[str] | None = None,
    known_policy_profiles: Mapping[str, int] | None = None,
    known_runtime_observation_ids: Set[str] | None = None,
    known_manual_evidence_refs: Set[str] | None = None,
    strict: bool = True,
) -> tuple[McsbCatalog, ...]:
    """Load every version directory and validate all implementation references."""

    if not root.is_dir():
        raise FileNotFoundError(f"MCSB catalog root not a directory: {root}")
    issues: list[McsbCatalogIssue] = []
    catalogs: list[McsbCatalog] = []
    for version_root in sorted(path for path in root.iterdir() if path.is_dir()):
        controls_raw, control_issues = _load_yaml(
            version_root / "controls.yaml", _CONTROL_VALIDATOR
        )
        crosswalk_raw, crosswalk_issues = _load_yaml(
            version_root / "crosswalk.yaml", _CROSSWALK_VALIDATOR
        )
        issues.extend(control_issues)
        issues.extend(crosswalk_issues)
        if controls_raw is None or crosswalk_raw is None or control_issues or crosswalk_issues:
            continue
        catalog, catalog_issues = _materialize_catalog(
            version_root,
            controls_raw,
            crosswalk_raw,
            known_rule_ids=known_rule_ids,
            known_policy_profiles=known_policy_profiles,
            known_runtime_observation_ids=known_runtime_observation_ids,
            known_manual_evidence_refs=known_manual_evidence_refs,
            strict=strict,
        )
        issues.extend(catalog_issues)
        if catalog is not None:
            catalogs.append(catalog)
    versions = [catalog.benchmark_version for catalog in catalogs]
    if len(versions) != len(set(versions)):
        issues.append(McsbCatalogIssue(root.as_posix(), "benchmark versions MUST be unique"))
    if issues:
        raise McsbCatalogError(issues)
    return tuple(catalogs)


def _materialize_catalog(
    version_root: Path,
    controls_raw: Mapping[str, Any],
    crosswalk_raw: Mapping[str, Any],
    *,
    known_rule_ids: Set[str] | None,
    known_policy_profiles: Mapping[str, int] | None,
    known_runtime_observation_ids: Set[str] | None,
    known_manual_evidence_refs: Set[str] | None,
    strict: bool,
) -> tuple[McsbCatalog | None, list[McsbCatalogIssue]]:
    issues: list[McsbCatalogIssue] = []
    version = str(controls_raw["benchmark_version"])
    if version_root.name != version:
        issues.append(
            McsbCatalogIssue(version_root.name, f"directory MUST match version {version!r}")
        )
    if crosswalk_raw["benchmark_version"] != version:
        issues.append(McsbCatalogIssue(version_root.name, "controls and crosswalk versions differ"))
    controls = tuple(
        McsbControl(id=str(item["id"]), domain=str(item["domain"]), title=str(item["title"]))
        for item in controls_raw["controls"]
    )
    control_ids = [control.id for control in controls]
    if len(control_ids) != len(set(control_ids)):
        issues.append(McsbCatalogIssue(version_root.name, "control ids MUST be unique"))
    for control in controls:
        if control.id.split("-", 1)[0] != control.domain:
            issues.append(
                McsbCatalogIssue(control.id, f"domain {control.domain!r} does not match id prefix")
            )
    if controls_raw["control_import_status"] == "metadata_only" and controls:
        issues.append(
            McsbCatalogIssue(version_root.name, "metadata_only catalog MUST have no controls")
        )
    raw_mappings = crosswalk_raw["mappings"]
    mapped_ids = [str(item["control_id"]) for item in raw_mappings]
    if len(mapped_ids) != len(set(mapped_ids)):
        issues.append(McsbCatalogIssue(version_root.name, "crosswalk control ids MUST be unique"))
    unknown_controls = sorted(set(mapped_ids) - set(control_ids))
    for control_id in unknown_controls:
        issues.append(McsbCatalogIssue(control_id, "crosswalk references an unknown control"))
    explicit = {str(item["control_id"]): item for item in raw_mappings}
    mappings = tuple(
        _mapping_from_raw(control.id, explicit.get(control.id)) for control in controls
    )
    issues.extend(_coverage_issues(mappings))
    issues.extend(
        _reference_issues(
            mappings,
            known_rule_ids=known_rule_ids,
            known_runtime_observation_ids=known_runtime_observation_ids,
            known_manual_evidence_refs=known_manual_evidence_refs,
            strict=strict,
        )
    )
    profiles = tuple(
        McsbPolicyProfile(
            profile_id=str(item["profile_id"]), policy_ref_count=int(item["policy_ref_count"])
        )
        for item in crosswalk_raw["policy_profiles"]
    )
    profile_ids = [profile.profile_id for profile in profiles]
    if len(profile_ids) != len(set(profile_ids)):
        issues.append(McsbCatalogIssue(version_root.name, "policy profile ids MUST be unique"))
    for profile in profiles:
        if known_policy_profiles is None:
            if strict:
                issues.append(
                    McsbCatalogIssue(profile.profile_id, "no policy-profile registry supplied")
                )
        elif known_policy_profiles.get(profile.profile_id) != profile.policy_ref_count:
            issues.append(
                McsbCatalogIssue(
                    profile.profile_id,
                    f"policy ref count {profile.policy_ref_count} does not match catalog",
                )
            )
    source_raw = controls_raw["source"]
    catalog = McsbCatalog(
        benchmark_version=version,
        status=str(controls_raw["status"]),
        control_import_status=str(controls_raw["control_import_status"]),
        title=str(controls_raw["title"]),
        source=McsbSource(**{key: source_raw.get(key) for key in McsbSource.__annotations__}),
        controls=controls,
        mappings=mappings,
        policy_profiles=profiles,
    )
    return catalog, issues


def _mapping_from_raw(control_id: str, raw: Mapping[str, Any] | None) -> McsbControlMapping:
    if raw is None:
        return McsbControlMapping(control_id=control_id, coverage=McsbCoverage.UNMAPPED)
    return McsbControlMapping(
        control_id=control_id,
        coverage=McsbCoverage(str(raw["coverage"])),
        rule_ids=tuple(str(value) for value in raw["rule_ids"]),
        runtime_observation_ids=tuple(str(value) for value in raw["runtime_observation_ids"]),
        manual_evidence_refs=tuple(str(value) for value in raw["manual_evidence_refs"]),
    )


def _coverage_issues(mappings: tuple[McsbControlMapping, ...]) -> list[McsbCatalogIssue]:
    issues: list[McsbCatalogIssue] = []
    for mapping in mappings:
        automated = bool(mapping.rule_ids or mapping.runtime_observation_ids)
        manual = bool(mapping.manual_evidence_refs)
        if mapping.coverage is McsbCoverage.AUTOMATED and not automated:
            issues.append(
                McsbCatalogIssue(
                    mapping.control_id,
                    "automated coverage needs an automated reference",
                )
            )
        elif mapping.coverage is McsbCoverage.PARTIAL and not (automated or manual):
            issues.append(
                McsbCatalogIssue(mapping.control_id, "partial coverage needs a reference")
            )
        elif mapping.coverage is McsbCoverage.MANUAL and (not manual or automated):
            issues.append(
                McsbCatalogIssue(
                    mapping.control_id,
                    "manual coverage needs only manual evidence",
                )
            )
        elif mapping.coverage is McsbCoverage.UNMAPPED and (automated or manual):
            issues.append(
                McsbCatalogIssue(
                    mapping.control_id,
                    "unmapped coverage MUST have no references",
                )
            )
    return issues


def _reference_issues(
    mappings: tuple[McsbControlMapping, ...],
    *,
    known_rule_ids: Set[str] | None,
    known_runtime_observation_ids: Set[str] | None,
    known_manual_evidence_refs: Set[str] | None,
    strict: bool,
) -> list[McsbCatalogIssue]:
    issues: list[McsbCatalogIssue] = []
    for mapping in mappings:
        issues.extend(
            _unknown_refs(
                mapping.control_id,
                "rule",
                mapping.rule_ids,
                known_rule_ids,
                strict=strict,
            )
        )
        issues.extend(
            _unknown_refs(
                mapping.control_id,
                "runtime observation",
                mapping.runtime_observation_ids,
                known_runtime_observation_ids,
                strict=strict,
            )
        )
        issues.extend(
            _unknown_refs(
                mapping.control_id,
                "manual evidence",
                mapping.manual_evidence_refs,
                known_manual_evidence_refs,
                strict=strict,
            )
        )
    return issues


def _unknown_refs(
    control_id: str,
    label: str,
    values: tuple[str, ...],
    registry: Set[str] | None,
    *,
    strict: bool,
) -> list[McsbCatalogIssue]:
    if values and registry is None and strict:
        return [McsbCatalogIssue(control_id, f"no {label} registry supplied")]
    if registry is None:
        return []
    return [
        McsbCatalogIssue(control_id, f"unknown {label} {value!r}")
        for value in values
        if value not in registry
    ]


__all__ = [
    "McsbCatalog",
    "McsbCatalogError",
    "McsbCatalogIssue",
    "McsbControl",
    "McsbControlMapping",
    "McsbCoverage",
    "McsbPolicyProfile",
    "McsbSource",
    "load_mcsb_catalogs",
]
