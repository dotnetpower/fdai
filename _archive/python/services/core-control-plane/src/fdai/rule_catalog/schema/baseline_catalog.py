"""Strict loaders for the two collected baseline artifact kinds.

`ConfigurationBaseline` is the hardened reference set a collector lands for one
resource type; it feeds T0 drift and what-if evaluation. `MeasurementBaseline`
is the performance reference from
``docs/roadmap/phases/phase-0-instrumentation.md``. The two share only the word
"baseline": they keep separate schemas, separate id namespaces, and separate
repository stores, and neither is ever loaded into the Rule catalog.

`ConfigurationBaseline` here is the authored or collected catalog artifact. The
runtime drift snapshot is the distinct
:class:`~fdai.core.detection.configuration_drift_models.FrozenConfigurationBaseline`.
The two are never interchangeable: this module's
:func:`evaluate_configuration_baseline_control_set` is the appropriate T0
consumer for the catalog artifact - it resolves ``controls`` (a list of Rule
ids) against the loaded Rule catalog - and it never manufactures a
``FrozenConfigurationBaseline`` from that list.

Both loaders are fail-closed: one invalid document fails the whole directory so
a partially valid store never reaches an evaluator.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping, Set
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_CONFIGURATION_SCHEMA = "configuration_baseline.schema.json"
_MEASUREMENT_SCHEMA = "measurement_baseline.schema.json"


@dataclass(frozen=True, slots=True)
class BaselineIssue:
    key: str
    message: str


class BaselineCatalogError(ValueError):
    """Aggregate schema, identity, and uniqueness failures."""

    def __init__(self, issues: list[BaselineIssue]) -> None:
        self.issues = tuple(issues)
        preview = "; ".join(f"{issue.key}: {issue.message}" for issue in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"baseline catalog load failed: {preview}{suffix}")


@dataclass(frozen=True, slots=True)
class ConfigurationBaselineProvenance:
    source_url: str
    resolved_ref: str
    content_hash: str
    license: str
    retrieved_at: datetime
    source_version: str | None = None
    mapped_by: str | None = None


@dataclass(frozen=True, slots=True)
class ConfigurationBaseline:
    """A hardened reference set of control ids for one resource type."""

    id: str
    version: str
    source: str
    resource_type: str
    controls: tuple[str, ...]
    provenance: ConfigurationBaselineProvenance
    title: str | None = None
    schema_version: str = "1.0.0"


@dataclass(frozen=True, slots=True)
class ConfigurationBaselineControlSetReport:
    """T0 what-if readiness for one catalog :class:`ConfigurationBaseline`.

    Resolves this reviewed control-set baseline's referenced Rule ids
    against the loaded Rule catalog (``rule-catalog/catalog/`` +
    ``rule-catalog/collected/``). This is the appropriate deterministic T0
    consumer for the catalog artifact: it answers "are every one of this
    hardened reference set's controls a real, evaluable Rule", which is a
    precondition for using the set in T0 what-if evaluation.

    This is intentionally **not** the runtime resource-attribute drift
    comparison in
    :class:`fdai.core.detection.configuration_drift_service.ConfigurationDriftService`.
    That service compares a separate
    :class:`fdai.core.detection.configuration_drift_models.FrozenConfigurationBaseline`
    (expected resource attributes + topology links) against live observed
    evidence, and never loads this catalog artifact. A catalog control-set
    baseline names *which checks* a hardened reference set expects to be
    evaluable; it carries no expected resource attribute values of its own,
    so it cannot itself produce a drift finding. Conflating the two would
    misrepresent a catalog reference list as a runtime evidence snapshot.
    """

    baseline_id: str
    resource_type: str
    resolved_controls: tuple[str, ...]
    unresolved_controls: tuple[str, ...]

    @property
    def is_resolved(self) -> bool:
        """``True`` when every referenced control id is a known Rule id."""

        return not self.unresolved_controls


def evaluate_configuration_baseline_control_set(
    baseline: ConfigurationBaseline,
    *,
    known_rule_ids: Set[str],
) -> ConfigurationBaselineControlSetReport:
    """Resolve one baseline's ``controls`` against the loaded Rule catalog.

    Read-only: never raises on an unresolved control id. Use
    :func:`require_resolved_configuration_baseline_control_set` for the
    fail-closed variant.
    """

    resolved = tuple(sorted(control for control in baseline.controls if control in known_rule_ids))
    unresolved = tuple(
        sorted(control for control in baseline.controls if control not in known_rule_ids)
    )
    return ConfigurationBaselineControlSetReport(
        baseline_id=baseline.id,
        resource_type=baseline.resource_type,
        resolved_controls=resolved,
        unresolved_controls=unresolved,
    )


def require_resolved_configuration_baseline_control_set(
    baseline: ConfigurationBaseline,
    *,
    known_rule_ids: Set[str],
) -> ConfigurationBaselineControlSetReport:
    """Fail-closed: raise :class:`BaselineCatalogError` on any unresolved control id."""

    report = evaluate_configuration_baseline_control_set(baseline, known_rule_ids=known_rule_ids)
    if report.unresolved_controls:
        raise BaselineCatalogError(
            [
                BaselineIssue(
                    key=f"{baseline.id}:{control}",
                    message="control id does not resolve to a known Rule id",
                )
                for control in report.unresolved_controls
            ]
        )
    return report


@dataclass(frozen=True, slots=True)
class MeasurementBaselineProvenance:
    measured_at: datetime
    measured_by: str


@dataclass(frozen=True, slots=True)
class MeasurementBaseline:
    """Recorded KPI values for one reference agent on a frozen scenario set."""

    id: str
    scenario_set: str
    reference_agent: str
    window: str
    metrics: Mapping[str, float]
    sample_size: int
    provenance: MeasurementBaselineProvenance
    schema_version: str = "1.0.0"


def load_configuration_baseline_from_mapping(raw: Mapping[str, Any]) -> ConfigurationBaseline:
    """Validate and materialize one configuration baseline document."""
    _reject_schema_errors(raw, _configuration_validator())
    provenance = raw["provenance"]
    return ConfigurationBaseline(
        id=str(raw["id"]),
        version=str(raw["version"]),
        source=str(raw["source"]),
        resource_type=str(raw["resource_type"]),
        controls=tuple(str(control) for control in raw["controls"]),
        provenance=ConfigurationBaselineProvenance(
            source_url=str(provenance["source_url"]),
            resolved_ref=str(provenance["resolved_ref"]),
            content_hash=str(provenance["content_hash"]),
            license=str(provenance["license"]),
            retrieved_at=_timestamp(provenance["retrieved_at"], key="provenance/retrieved_at"),
            source_version=_optional_text(provenance.get("source_version")),
            mapped_by=_optional_text(provenance.get("mapped_by")),
        ),
        title=_optional_text(raw.get("title")),
        schema_version=str(raw["schema_version"]),
    )


def load_measurement_baseline_from_mapping(raw: Mapping[str, Any]) -> MeasurementBaseline:
    """Validate and materialize one measurement baseline document."""
    _reject_schema_errors(raw, _measurement_validator())
    provenance = raw["provenance"]
    return MeasurementBaseline(
        id=str(raw["id"]),
        scenario_set=str(raw["scenario_set"]),
        reference_agent=str(raw["reference_agent"]),
        window=str(raw["window"]),
        metrics={str(key): float(value) for key, value in raw["metrics"].items()},
        sample_size=int(raw["sample_size"]),
        provenance=MeasurementBaselineProvenance(
            measured_at=_timestamp(provenance["measured_at"], key="provenance/measured_at"),
            measured_by=str(provenance["measured_by"]),
        ),
        schema_version=str(raw["schema_version"]),
    )


def load_configuration_baseline_catalog(root: Path) -> tuple[ConfigurationBaseline, ...]:
    """Load every configuration baseline under ``root`` in id order.

    A missing directory loads as empty; the store is optional upstream.
    """
    loaded = [
        (path, load_configuration_baseline_from_mapping(document))
        for path, document in _iter_documents(root)
    ]
    _reject_duplicate_ids((path, item.id) for path, item in loaded)
    return tuple(sorted((item for _, item in loaded), key=lambda item: item.id))


def load_measurement_baseline_catalog(root: Path) -> tuple[MeasurementBaseline, ...]:
    """Load every measurement baseline under ``root`` in id order."""
    loaded = [
        (path, load_measurement_baseline_from_mapping(document))
        for path, document in _iter_documents(root)
    ]
    _reject_duplicate_ids((path, item.id) for path, item in loaded)
    return tuple(sorted((item for _, item in loaded), key=lambda item: item.id))


def _iter_documents(root: Path) -> Iterator[tuple[Path, Mapping[str, Any]]]:
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.yaml")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw is None:
            continue
        if not isinstance(raw, Mapping):
            raise BaselineCatalogError(
                [BaselineIssue(key=path.name, message="document MUST be a mapping")]
            )
        yield path, raw


def _reject_duplicate_ids(entries: Iterable[tuple[Path, str]]) -> None:
    seen: dict[str, str] = {}
    issues: list[BaselineIssue] = []
    for path, identifier in entries:
        prior = seen.get(identifier)
        if prior is not None:
            issues.append(
                BaselineIssue(
                    key=path.name,
                    message=f"duplicate baseline id {identifier!r} (also in {prior})",
                )
            )
            continue
        seen[identifier] = path.name
    if issues:
        raise BaselineCatalogError(issues)


def _reject_schema_errors(raw: Mapping[str, Any], validator: Draft202012Validator) -> None:
    issues = [
        BaselineIssue(
            key="/".join(str(part) for part in error.path) or "<root>",
            message=error.message,
        )
        for error in sorted(validator.iter_errors(raw), key=lambda item: list(item.path))
    ]
    if issues:
        raise BaselineCatalogError(issues)


def _timestamp(value: Any, *, key: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise BaselineCatalogError(
                [BaselineIssue(key=key, message=f"not a valid RFC 3339 timestamp: {value!r}")]
            ) from exc
    if parsed.tzinfo is None:
        raise BaselineCatalogError(
            [BaselineIssue(key=key, message="timestamp MUST be timezone-aware (RFC 3339)")]
        )
    return parsed


def _optional_text(value: Any) -> str | None:
    return None if value is None else str(value)


def _configuration_validator() -> Draft202012Validator:
    return _validator(_CONFIGURATION_SCHEMA)


def _measurement_validator() -> Draft202012Validator:
    return _validator(_MEASUREMENT_SCHEMA)


@cache
def _validator(schema_file: str) -> Draft202012Validator:
    schema = json.loads(
        resources.files(_SCHEMA_PACKAGE).joinpath(schema_file).read_text(encoding="utf-8")
    )
    return Draft202012Validator(schema, format_checker=FormatChecker())


__all__ = [
    "BaselineCatalogError",
    "BaselineIssue",
    "ConfigurationBaseline",
    "ConfigurationBaselineControlSetReport",
    "ConfigurationBaselineProvenance",
    "MeasurementBaseline",
    "MeasurementBaselineProvenance",
    "evaluate_configuration_baseline_control_set",
    "load_configuration_baseline_catalog",
    "load_configuration_baseline_from_mapping",
    "load_measurement_baseline_catalog",
    "load_measurement_baseline_from_mapping",
    "require_resolved_configuration_baseline_control_set",
]
