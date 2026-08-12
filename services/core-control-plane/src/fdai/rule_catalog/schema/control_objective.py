"""Strict, non-authoritative ControlObjective catalog contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fdai.shared.contracts.models import OntologyProvenance

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_IDENTIFIER_PATTERN = r"^[a-z][a-z0-9._-]{0,127}$"
_REFERENCE_PATTERN = r"^[A-Za-z][A-Za-z0-9._:@/-]{0,255}$"
_SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"
_MAX_DESCRIPTION_LENGTH = 4096
_MAX_REFERENCES = 64


class ControlObjectiveState(StrEnum):
    CANDIDATE = "candidate"
    REVIEWED = "reviewed"
    PROMOTED = "promoted"
    RETIRED = "retired"
    SUPERSEDED = "superseded"


class ApplicableOntology(BaseModel):
    """Reviewed ontology identities that bound one objective's applicability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    object_type: Annotated[str, Field(pattern=_REFERENCE_PATTERN)]
    resource_types: tuple[Annotated[str, Field(pattern=_IDENTIFIER_PATTERN)], ...] = Field(
        min_length=1, max_length=_MAX_REFERENCES
    )
    property_refs: tuple[Annotated[str, Field(pattern=_REFERENCE_PATTERN)], ...] = Field(
        min_length=1, max_length=_MAX_REFERENCES
    )

    @model_validator(mode="after")
    def require_canonical_references(self) -> ApplicableOntology:
        for name, values in (
            ("resource_types", self.resource_types),
            ("property_refs", self.property_refs),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{name} MUST be unique and ordered")
        return self


class ControlObjective(BaseModel):
    """Provider-neutral intent that can narrow Rule candidates but grants no authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[str, Field(pattern=_SEMVER_PATTERN)] = "1.0.0"
    id: Annotated[str, Field(pattern=_IDENTIFIER_PATTERN)]
    version: Annotated[str, Field(pattern=_SEMVER_PATTERN)]
    title: Annotated[str, Field(min_length=1, max_length=256)]
    description: Annotated[str, Field(min_length=1, max_length=_MAX_DESCRIPTION_LENGTH)]
    operating_domain: Annotated[str, Field(pattern=_IDENTIFIER_PATTERN)]
    protected_outcome_refs: tuple[Annotated[str, Field(pattern=_REFERENCE_PATTERN)], ...] = Field(
        min_length=1, max_length=_MAX_REFERENCES
    )
    applicable_ontology: ApplicableOntology
    predicate_family: Annotated[str, Field(min_length=1, max_length=1024)]
    state: ControlObjectiveState = ControlObjectiveState.CANDIDATE
    supersedes: Annotated[str, Field(pattern=_REFERENCE_PATTERN)] | None = None
    semantic_surface_refs: tuple[Annotated[str, Field(pattern=_REFERENCE_PATTERN)], ...] = Field(
        default=(), max_length=_MAX_REFERENCES
    )
    content_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    provenance: OntologyProvenance

    @model_validator(mode="after")
    def require_canonical_references(self) -> ControlObjective:
        for name, values in (
            ("protected_outcome_refs", self.protected_outcome_refs),
            ("semantic_surface_refs", self.semantic_surface_refs),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{name} MUST be unique and ordered")
        return self

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"


@dataclass(frozen=True, slots=True)
class ControlObjectiveIssue:
    key: str
    message: str


class ControlObjectiveCatalogError(ValueError):
    """Aggregate error surfaced when objective catalog validation fails."""

    def __init__(self, issues: list[ControlObjectiveIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{issue.key}: {issue.message}" for issue in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"control-objective catalog validation failed: {preview}{suffix}")


def control_objective_content_hash(objective: ControlObjective) -> str:
    """Return canonical identity without self-referential digest or provenance fields."""

    payload = objective.model_dump(
        mode="json",
        exclude={"content_digest", "provenance"},
        exclude_none=True,
    )
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def load_control_objective_from_mapping(
    raw: Mapping[str, Any],
    *,
    operating_domains: frozenset[str],
    object_type_names: frozenset[str],
    resource_type_ids: frozenset[str],
    property_refs: frozenset[str],
    objective_refs: frozenset[str] = frozenset(),
    origin: str = "<mapping>",
) -> ControlObjective:
    """Validate one objective and all supplied catalog cross-references."""

    try:
        objective = ControlObjective.model_validate(raw)
    except ValueError as exc:
        issues = _pydantic_issues(exc, origin)
        raise ControlObjectiveCatalogError(issues) from exc

    issues: list[ControlObjectiveIssue] = []
    if objective.operating_domain not in operating_domains:
        issues.append(
            ControlObjectiveIssue(
                key=f"{origin}:operating_domain",
                message=f"unknown operating domain {objective.operating_domain!r}",
            )
        )
    if objective.applicable_ontology.object_type not in object_type_names:
        issues.append(
            ControlObjectiveIssue(
                key=f"{origin}:applicable_ontology.object_type",
                message=f"unknown ObjectType {objective.applicable_ontology.object_type!r}",
            )
        )
    for index, resource_type in enumerate(objective.applicable_ontology.resource_types):
        if resource_type not in resource_type_ids:
            issues.append(
                ControlObjectiveIssue(
                    key=f"{origin}:applicable_ontology.resource_types[{index}]",
                    message=f"unknown resource type {resource_type!r}",
                )
            )
    for index, property_ref in enumerate(objective.applicable_ontology.property_refs):
        if property_ref not in property_refs:
            issues.append(
                ControlObjectiveIssue(
                    key=f"{origin}:applicable_ontology.property_refs[{index}]",
                    message=f"unknown Property reference {property_ref!r}",
                )
            )
    if objective.supersedes is not None and objective.supersedes not in objective_refs:
        issues.append(
            ControlObjectiveIssue(
                key=f"{origin}:supersedes",
                message=f"unknown superseded objective {objective.supersedes!r}",
            )
        )

    expected_digest = control_objective_content_hash(objective)
    if objective.content_digest != expected_digest:
        issues.append(
            ControlObjectiveIssue(
                key=f"{origin}:content_digest",
                message=(
                    f"content_digest mismatch: expected {expected_digest}, "
                    f"got {objective.content_digest}"
                ),
            )
        )
    if objective.provenance.content_hash != expected_digest:
        issues.append(
            ControlObjectiveIssue(
                key=f"{origin}:provenance.content_hash",
                message=(
                    f"provenance.content_hash mismatch: expected {expected_digest}, "
                    f"got {objective.provenance.content_hash}"
                ),
            )
        )
    if issues:
        raise ControlObjectiveCatalogError(issues)
    return objective


def load_control_objective_catalog(
    root: Path,
    *,
    operating_domains: frozenset[str],
    object_type_names: frozenset[str],
    resource_type_ids: frozenset[str],
    property_refs: frozenset[str],
) -> tuple[ControlObjective, ...]:
    """Load a complete objective catalog, aggregating invalid files and identities."""

    issues: list[ControlObjectiveIssue] = []
    raw_entries: list[tuple[Path, Mapping[str, Any]]] = []
    declared_refs: set[str] = set()
    for path in _iter_yaml_files(root):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            issues.append(ControlObjectiveIssue(path.name, f"invalid YAML: {exc}"))
            continue
        if not isinstance(raw, Mapping):
            issues.append(ControlObjectiveIssue(path.name, "top-level must be a mapping"))
            continue
        objective_id = raw.get("id")
        version = raw.get("version")
        if isinstance(objective_id, str) and isinstance(version, str):
            objective_ref = f"{objective_id}@{version}"
            if objective_ref in declared_refs:
                issues.append(
                    ControlObjectiveIssue(path.name, f"duplicate objective ref {objective_ref!r}")
                )
            declared_refs.add(objective_ref)
        raw_entries.append((path, raw))

    loaded: list[ControlObjective] = []
    for path, raw in raw_entries:
        try:
            loaded.append(
                load_control_objective_from_mapping(
                    raw,
                    operating_domains=operating_domains,
                    object_type_names=object_type_names,
                    resource_type_ids=resource_type_ids,
                    property_refs=property_refs,
                    objective_refs=frozenset(declared_refs),
                    origin=path.name,
                )
            )
        except ControlObjectiveCatalogError as exc:
            issues.extend(exc.issues)
    if issues:
        raise ControlObjectiveCatalogError(issues)
    return tuple(sorted(loaded, key=lambda objective: objective.ref))


def validate_control_objective_transition(
    previous: ControlObjective,
    current: ControlObjective,
) -> None:
    """Reject lifecycle transitions that bypass review or reactivate terminal records."""

    if previous.ref != current.ref:
        raise ValueError(
            "ControlObjective lifecycle transition MUST retain the exact objective ref"
        )
    allowed = {
        ControlObjectiveState.CANDIDATE: {
            ControlObjectiveState.REVIEWED,
            ControlObjectiveState.RETIRED,
        },
        ControlObjectiveState.REVIEWED: {
            ControlObjectiveState.PROMOTED,
            ControlObjectiveState.RETIRED,
        },
        ControlObjectiveState.PROMOTED: {
            ControlObjectiveState.RETIRED,
            ControlObjectiveState.SUPERSEDED,
        },
        ControlObjectiveState.RETIRED: set(),
        ControlObjectiveState.SUPERSEDED: set(),
    }
    if current.state != previous.state and current.state not in allowed[previous.state]:
        raise ValueError(
            f"ControlObjective state transition {previous.state.value!r} -> "
            f"{current.state.value!r} is not allowed"
        )


def _pydantic_issues(exc: ValueError, origin: str) -> list[ControlObjectiveIssue]:
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return [ControlObjectiveIssue(f"{origin}:<root>", str(exc))]
    return [
        ControlObjectiveIssue(
            key=f"{origin}:{'.'.join(str(part) for part in error.get('loc', ())) or '<root>'}",
            message=error["msg"],
        )
        for error in errors()
    ]


def _iter_yaml_files(root: Path) -> Iterator[Path]:
    yield from sorted(root.glob("*.yaml"))


__all__ = [
    "ApplicableOntology",
    "ControlObjective",
    "ControlObjectiveCatalogError",
    "ControlObjectiveIssue",
    "ControlObjectiveState",
    "control_objective_content_hash",
    "load_control_objective_catalog",
    "load_control_objective_from_mapping",
    "validate_control_objective_transition",
]
