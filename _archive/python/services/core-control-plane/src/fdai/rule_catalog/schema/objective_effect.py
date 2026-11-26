"""Digest-bound objective-effect catalog records for grounded arbitration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fdai.rule_catalog.schema.catalog_digest import canonical_catalog_digest
from fdai.shared.contracts.models import OntologyProvenance

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_IDENTIFIER_PATTERN = r"^[a-z][a-z0-9._-]{0,127}$"
_REFERENCE_PATTERN = r"^[A-Za-z][A-Za-z0-9._:@/-]{0,255}$"
_ACTION_TYPE_PATTERN = r"^[a-z][a-z0-9_\.\-]{0,79}$"
_SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"
_METRIC_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"
_MAX_EFFECTS = 16


class ObjectiveEffectBindingState(StrEnum):
    CANDIDATE = "candidate"
    REVIEWED = "reviewed"
    RETIRED = "retired"


class RulePin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: Annotated[str, Field(pattern=_REFERENCE_PATTERN)]
    content_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]


class CatalogObjectiveEffect(BaseModel):
    """Signed expected utility emitted by one rule/action pair."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    objective_kind: Annotated[str, Field(pattern=_METRIC_PATTERN)]
    metric: Annotated[str, Field(pattern=_METRIC_PATTERN)]
    utility: Annotated[float, Field(ge=-1.0, le=1.0)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    expected_min: Annotated[float, Field(ge=-1.0, le=1.0)]
    expected_max: Annotated[float, Field(ge=-1.0, le=1.0)]
    observation_window_seconds: Annotated[int, Field(ge=1, le=86_400)]

    @model_validator(mode="after")
    def validate_range(self) -> CatalogObjectiveEffect:
        if self.expected_min > self.expected_max:
            raise ValueError("objective effect expected_min MUST be <= expected_max")
        return self


class RuleObjectiveEffectBinding(BaseModel):
    """Reviewed, digest-bound effects for one exact Rule and ActionType."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[str, Field(pattern=_SEMVER_PATTERN)] = "1.0.0"
    id: Annotated[str, Field(pattern=_IDENTIFIER_PATTERN)]
    version: Annotated[str, Field(pattern=_SEMVER_PATTERN)]
    rule: RulePin
    action_type: Annotated[str, Field(pattern=_ACTION_TYPE_PATTERN)]
    effects: tuple[CatalogObjectiveEffect, ...] = Field(min_length=1, max_length=_MAX_EFFECTS)
    reviewer: Annotated[str, Field(min_length=1, max_length=256)]
    state: ObjectiveEffectBindingState = ObjectiveEffectBindingState.CANDIDATE
    content_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    provenance: OntologyProvenance

    @model_validator(mode="after")
    def validate_binding(self) -> RuleObjectiveEffectBinding:
        objective_kinds = tuple(effect.objective_kind for effect in self.effects)
        if objective_kinds != tuple(sorted(set(objective_kinds))):
            raise ValueError("objective effects MUST carry one ordered effect per kind")
        return self

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"


@dataclass(frozen=True, slots=True)
class ObjectiveEffectIssue:
    key: str
    message: str


class ObjectiveEffectCatalogError(ValueError):
    def __init__(self, issues: list[ObjectiveEffectIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{issue.key}: {issue.message}" for issue in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"objective-effect catalog validation failed: {preview}{suffix}")


def objective_effect_content_hash(binding: RuleObjectiveEffectBinding) -> str:
    """Return the canonical digest pinning one effect binding."""

    return canonical_catalog_digest(binding)


def load_objective_effect_from_mapping(
    raw: Mapping[str, Any],
    *,
    rule_digests: Mapping[str, str],
    action_type_names: frozenset[str],
    origin: str = "<memory>",
) -> RuleObjectiveEffectBinding:
    issues: list[ObjectiveEffectIssue] = []
    try:
        binding = RuleObjectiveEffectBinding.model_validate(raw)
    except Exception as exc:
        issues.append(ObjectiveEffectIssue(origin, str(exc)))
        raise ObjectiveEffectCatalogError(issues) from exc

    expected_rule_digest = rule_digests.get(binding.rule.ref)
    if expected_rule_digest is None:
        issues.append(
            ObjectiveEffectIssue(
                key=f"{origin}:rule.ref",
                message=f"unknown Rule version {binding.rule.ref!r}",
            )
        )
    elif binding.rule.content_digest != expected_rule_digest:
        issues.append(
            ObjectiveEffectIssue(
                key=f"{origin}:rule.content_digest",
                message=f"rule digest mismatch: expected {expected_rule_digest}",
            )
        )
    if binding.action_type not in action_type_names:
        issues.append(
            ObjectiveEffectIssue(
                key=f"{origin}:action_type",
                message=f"unknown ActionType {binding.action_type!r}",
            )
        )
    expected_digest = objective_effect_content_hash(binding)
    if binding.content_digest != expected_digest:
        issues.append(
            ObjectiveEffectIssue(
                key=f"{origin}:content_digest",
                message=f"content_digest mismatch: expected {expected_digest}",
            )
        )
    if binding.provenance.content_hash != binding.content_digest:
        issues.append(
            ObjectiveEffectIssue(
                key=f"{origin}:provenance.content_hash",
                message="provenance content_hash MUST match content_digest",
            )
        )
    if issues:
        raise ObjectiveEffectCatalogError(issues)
    return binding


def load_objective_effect_catalog(
    root: Path,
    *,
    rule_digests: Mapping[str, str],
    action_type_names: frozenset[str],
    required_bindings: frozenset[tuple[str, str]] = frozenset(),
    states: frozenset[ObjectiveEffectBindingState] = frozenset(
        {ObjectiveEffectBindingState.REVIEWED}
    ),
) -> tuple[RuleObjectiveEffectBinding, ...]:
    """Load effect bindings and fail closed when required reviewed records are absent."""

    issues: list[ObjectiveEffectIssue] = []
    bindings: list[RuleObjectiveEffectBinding] = []
    seen_refs: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    for path in sorted(root.glob("*.yaml")):
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except OSError as exc:
            issues.append(ObjectiveEffectIssue(path.name, str(exc)))
            continue
        if not isinstance(loaded, Mapping):
            issues.append(ObjectiveEffectIssue(path.name, "objective-effect file MUST be a map"))
            continue
        try:
            binding = load_objective_effect_from_mapping(
                loaded,
                rule_digests=rule_digests,
                action_type_names=action_type_names,
                origin=path.name,
            )
        except ObjectiveEffectCatalogError as exc:
            issues.extend(exc.issues)
            continue
        if binding.ref in seen_refs:
            issues.append(
                ObjectiveEffectIssue(
                    key=f"{path.name}:id",
                    message=f"duplicate objective-effect binding {binding.ref!r}",
                )
            )
        seen_refs.add(binding.ref)
        key = (binding.rule.ref.split("@", 1)[0], binding.action_type)
        if binding.state in states:
            if key in seen_pairs:
                issues.append(
                    ObjectiveEffectIssue(
                        key=f"{path.name}:rule",
                        message=f"duplicate reviewed objective-effect binding for {key!r}",
                    )
                )
            seen_pairs.add(key)
            bindings.append(binding)
    missing = required_bindings - seen_pairs
    for rule_id, action_type in sorted(missing):
        issues.append(
            ObjectiveEffectIssue(
                key=f"required_binding:{rule_id}:{action_type}",
                message="missing reviewed objective-effect binding",
            )
        )
    if issues:
        raise ObjectiveEffectCatalogError(issues)
    return tuple(sorted(bindings, key=lambda item: item.ref))


def effect_record_for(
    bindings: Sequence[RuleObjectiveEffectBinding],
    *,
    rule_id: str,
    action_type: str,
) -> RuleObjectiveEffectBinding:
    """Resolve exactly one reviewed binding for a replay-produced Rule and ActionType."""

    found = tuple(
        binding
        for binding in bindings
        if binding.rule.ref.split("@", 1)[0] == rule_id and binding.action_type == action_type
    )
    if len(found) != 1:
        raise ObjectiveEffectCatalogError(
            [
                ObjectiveEffectIssue(
                    key=f"effect_record:{rule_id}:{action_type}",
                    message=f"expected exactly one objective-effect binding, got {len(found)}",
                )
            ]
        )
    return found[0]


__all__ = [
    "CatalogObjectiveEffect",
    "ObjectiveEffectBindingState",
    "ObjectiveEffectCatalogError",
    "ObjectiveEffectIssue",
    "RuleObjectiveEffectBinding",
    "effect_record_for",
    "load_objective_effect_catalog",
    "load_objective_effect_from_mapping",
    "objective_effect_content_hash",
]
