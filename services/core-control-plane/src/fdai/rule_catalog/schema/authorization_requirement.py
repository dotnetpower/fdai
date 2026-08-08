"""Strict provider-neutral execution-authorization requirement catalog."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from fdai.rule_catalog.schema.provenance import Provenance


@dataclass(frozen=True, slots=True)
class AuthorizationRequirementSpec:
    requirement_id: str
    version: str
    capability_id: str
    action_type_ids: frozenset[str]
    resource_types: frozenset[str]
    scope_expressions: tuple[str, ...]
    execution_profile: str
    provenance: Provenance

    def applies_to(self, *, action_type_id: str, resource_type: str) -> bool:
        return action_type_id in self.action_type_ids and resource_type in self.resource_types


@dataclass(frozen=True, slots=True)
class AuthorizationRequirementIssue:
    key: str
    message: str


class AuthorizationRequirementLoadError(ValueError):
    def __init__(self, issues: list[AuthorizationRequirementIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{item.key}: {item.message}" for item in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"authorization requirement catalog invalid: {preview}{suffix}")


def _load_schema() -> dict[str, Any]:
    raw = (
        resources.files("fdai.rule_catalog.schema")
        .joinpath("execution_authorization_requirement.schema.json")
        .read_text(encoding="utf-8")
    )
    return json.loads(raw)  # type: ignore[no-any-return]


_VALIDATOR = Draft202012Validator(_load_schema())


def load_authorization_requirement_from_mapping(
    raw: Mapping[str, Any],
) -> AuthorizationRequirementSpec:
    issues = [
        AuthorizationRequirementIssue(
            key="/".join(str(part) for part in error.path) or "<root>",
            message=error.message,
        )
        for error in sorted(_VALIDATOR.iter_errors(raw), key=lambda item: list(item.path))
    ]
    if issues:
        raise AuthorizationRequirementLoadError(issues)
    try:
        return AuthorizationRequirementSpec(
            requirement_id=str(raw["id"]),
            version=str(raw["version"]),
            capability_id=str(raw["capability_id"]),
            action_type_ids=frozenset(raw["action_type_ids"]),
            resource_types=frozenset(raw["resource_types"]),
            scope_expressions=tuple(raw["scope_expressions"]),
            execution_profile=str(raw["execution_profile"]),
            provenance=Provenance.from_mapping(raw["provenance"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorizationRequirementLoadError(
            [AuthorizationRequirementIssue("<mapping>", str(exc))]
        ) from exc


def load_authorization_requirement_catalog(
    root: Path,
    *,
    known_action_type_ids: frozenset[str],
    known_resource_types: frozenset[str],
    known_capability_ids: frozenset[str],
    known_execution_profiles: frozenset[str],
) -> tuple[AuthorizationRequirementSpec, ...]:
    loaded: list[AuthorizationRequirementSpec] = []
    issues: list[AuthorizationRequirementIssue] = []
    seen: dict[str, str] = {}
    for path in sorted((*root.glob("*.yaml"), *root.glob("*.yml"))):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            issues.append(AuthorizationRequirementIssue(path.name, f"invalid YAML: {exc}"))
            continue
        if not isinstance(raw, Mapping):
            issues.append(AuthorizationRequirementIssue(path.name, "top-level MUST be a mapping"))
            continue
        try:
            requirement = load_authorization_requirement_from_mapping(raw)
        except AuthorizationRequirementLoadError as exc:
            issues.extend(
                AuthorizationRequirementIssue(f"{path.name}:{item.key}", item.message)
                for item in exc.issues
            )
            continue
        prior = seen.get(requirement.requirement_id)
        if prior is not None:
            issues.append(
                AuthorizationRequirementIssue(
                    path.name,
                    f"duplicate requirement id {requirement.requirement_id!r} (also in {prior})",
                )
            )
            continue
        seen[requirement.requirement_id] = path.name
        references = (
            ("action_type_ids", requirement.action_type_ids - known_action_type_ids),
            ("resource_types", requirement.resource_types - known_resource_types),
            ("capability_id", {requirement.capability_id} - known_capability_ids),
            ("execution_profile", {requirement.execution_profile} - known_execution_profiles),
        )
        unknown = False
        for key, values in references:
            if values:
                unknown = True
                issues.append(
                    AuthorizationRequirementIssue(
                        f"{path.name}:{key}", f"unknown references: {sorted(values)}"
                    )
                )
        if not unknown:
            loaded.append(requirement)
    if issues:
        raise AuthorizationRequirementLoadError(issues)
    return tuple(sorted(loaded, key=lambda item: item.requirement_id))


__all__ = [
    "AuthorizationRequirementIssue",
    "AuthorizationRequirementLoadError",
    "AuthorizationRequirementSpec",
    "load_authorization_requirement_catalog",
    "load_authorization_requirement_from_mapping",
]
