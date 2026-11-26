"""Catalog-as-code execution-authorization assignments and strict loader."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from fdai.rule_catalog.schema.provenance import Provenance
from fdai.rule_catalog.schema.scope import (
    ResourceContext,
    Scope,
    ScopeBinding,
    ScopeLevel,
    ScopeMatcher,
    ScopeRef,
    ScopeSelector,
)


class AuthorizationPosture(StrEnum):
    PROHIBIT = "prohibit"
    DELEGATE_MANUAL = "delegate_manual"
    PREPROVISIONED_ONLY = "preprovisioned_only"
    REQUEST_JIT = "request_jit"
    STANDING = "standing"


class AuthorizationEnforcement(StrEnum):
    DO_NOT_ENFORCE = "do-not-enforce"
    ENFORCE = "enforce"


class GrantMode(StrEnum):
    ACTION_BOUND = "action_bound"
    TIME_BOUND = "time_bound"
    STANDING = "standing"


class AuthorizationScopeLevel(IntEnum):
    """Scope specificity ordered broadest to narrowest for conservative max()."""

    ORGANIZATION = 0
    ACCOUNT = 1
    RESOURCE_GROUP = 2
    RESOURCE = 3


@dataclass(frozen=True, slots=True)
class AuthorizationConstraints:
    allowed_grant_modes: frozenset[GrantMode]
    max_scope: AuthorizationScopeLevel
    max_duration_seconds: int
    quorum: int = 1
    approver_roles: frozenset[str] = frozenset()
    required_evidence: frozenset[str] = frozenset()
    require_effective_probe: bool = True
    exemptible: bool = False

    def __post_init__(self) -> None:
        if not self.allowed_grant_modes:
            raise ValueError("authorization constraints MUST allow at least one grant mode")
        if self.max_duration_seconds < 1:
            raise ValueError("authorization max_duration_seconds MUST be positive")
        if self.quorum < 1:
            raise ValueError("authorization quorum MUST be positive")
        if any(not value.strip() for value in self.approver_roles | self.required_evidence):
            raise ValueError("authorization constraint labels MUST be non-empty")


@dataclass(frozen=True, slots=True)
class AuthorizationPolicyAssignment:
    assignment_id: str
    capabilities: frozenset[str]
    execution_profiles: frozenset[str]
    scope: ScopeMatcher
    posture: AuthorizationPosture
    constraints: AuthorizationConstraints
    enforcement: AuthorizationEnforcement = AuthorizationEnforcement.DO_NOT_ENFORCE
    version: str = "1.0.0"
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if not self.assignment_id.strip() or not self.version.strip():
            raise ValueError("authorization assignment id and version MUST be non-empty")
        if not self.capabilities or not self.execution_profiles:
            raise ValueError("authorization assignment bindings MUST be non-empty")

    def applies_to(
        self,
        *,
        capability_id: str,
        execution_profile: str,
        resource: ResourceContext,
    ) -> bool:
        return (
            capability_id in self.capabilities
            and execution_profile in self.execution_profiles
            and self.scope.covers(resource)
        )


@dataclass(frozen=True, slots=True)
class AuthorizationAssignmentIssue:
    key: str
    message: str


class AuthorizationAssignmentLoadError(ValueError):
    def __init__(self, issues: list[AuthorizationAssignmentIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{item.key}: {item.message}" for item in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"execution authorization assignment invalid: {preview}{suffix}")


_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_SCHEMA_FILE = "execution_authorization.schema.json"
_LEVEL_BY_LABEL = {
    "organization": ScopeLevel.ORGANIZATION,
    "account": ScopeLevel.ACCOUNT,
    "resource-group": ScopeLevel.RESOURCE_GROUP,
    "resource": ScopeLevel.RESOURCE,
}
_AUTHORIZATION_LEVEL_BY_LABEL = {
    "organization": AuthorizationScopeLevel.ORGANIZATION,
    "account": AuthorizationScopeLevel.ACCOUNT,
    "resource-group": AuthorizationScopeLevel.RESOURCE_GROUP,
    "resource": AuthorizationScopeLevel.RESOURCE,
}


def _load_schema() -> dict[str, Any]:
    raw = resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_FILE).read_text(encoding="utf-8")
    return json.loads(raw)  # type: ignore[no-any-return]


_VALIDATOR = Draft202012Validator(_load_schema())


def _selector(raw: Mapping[str, Any] | None) -> ScopeSelector | None:
    if raw is None:
        return None
    return ScopeSelector(
        resource_types=frozenset(raw.get("resource_types", ())),
        tags=dict(raw.get("tags", {})),
        resource_ids=frozenset(raw.get("resource_ids", ())),
    )


def _scope(raw: Mapping[str, Any]) -> ScopeMatcher:
    if "include" in raw:
        return ScopeBinding(
            includes=tuple(ScopeRef.parse(value) for value in raw["include"]),
            excludes=tuple(ScopeRef.parse(value) for value in raw.get("exclude", ())),
            selector=_selector(raw.get("selector")),
        )
    return Scope(
        level=_LEVEL_BY_LABEL[str(raw["level"])],
        id=str(raw["id"]),
        selector=_selector(raw.get("selector")),
        excludes=frozenset(raw.get("excludes", ())),
    )


def load_authorization_assignment_from_mapping(
    raw: Mapping[str, Any],
) -> AuthorizationPolicyAssignment:
    issues = [
        AuthorizationAssignmentIssue(
            key="/".join(str(part) for part in error.path) or "<root>",
            message=error.message,
        )
        for error in sorted(_VALIDATOR.iter_errors(raw), key=lambda item: list(item.path))
    ]
    if issues:
        raise AuthorizationAssignmentLoadError(issues)
    try:
        scope = _scope(raw["scope"])
        constraints_raw = raw["constraints"]
        provenance_raw = raw.get("provenance")
        provenance = Provenance.from_mapping(provenance_raw) if provenance_raw is not None else None
        constraints = AuthorizationConstraints(
            allowed_grant_modes=frozenset(
                GrantMode(value) for value in constraints_raw["allowed_grant_modes"]
            ),
            max_scope=_AUTHORIZATION_LEVEL_BY_LABEL[constraints_raw["max_scope"]],
            max_duration_seconds=int(constraints_raw["max_duration_seconds"]),
            quorum=int(constraints_raw.get("quorum", 1)),
            approver_roles=frozenset(constraints_raw.get("approver_roles", ())),
            required_evidence=frozenset(constraints_raw.get("required_evidence", ())),
            require_effective_probe=bool(constraints_raw.get("require_effective_probe", True)),
            exemptible=bool(constraints_raw.get("exemptible", False)),
        )
        return AuthorizationPolicyAssignment(
            assignment_id=str(raw["id"]),
            capabilities=frozenset(raw["capabilities"]),
            execution_profiles=frozenset(raw["execution_profiles"]),
            scope=scope,
            posture=AuthorizationPosture(raw["posture"]),
            constraints=constraints,
            enforcement=AuthorizationEnforcement(
                raw.get("enforcement", AuthorizationEnforcement.DO_NOT_ENFORCE.value)
            ),
            version=str(raw["version"]),
            provenance=provenance,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorizationAssignmentLoadError(
            [AuthorizationAssignmentIssue(key="<mapping>", message=str(exc))]
        ) from exc


def load_authorization_assignment_catalog(
    root: Path,
    *,
    known_capability_ids: frozenset[str],
    known_execution_profiles: frozenset[str],
) -> tuple[AuthorizationPolicyAssignment, ...]:
    """Load all assignment YAML files with duplicate and reference checks."""

    loaded: list[AuthorizationPolicyAssignment] = []
    issues: list[AuthorizationAssignmentIssue] = []
    seen: dict[str, str] = {}
    paths = sorted((*root.glob("*.yaml"), *root.glob("*.yml")))
    for path in paths:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            issues.append(AuthorizationAssignmentIssue(path.name, f"invalid YAML: {exc}"))
            continue
        if not isinstance(raw, Mapping):
            issues.append(AuthorizationAssignmentIssue(path.name, "top-level MUST be a mapping"))
            continue
        try:
            assignment = load_authorization_assignment_from_mapping(raw)
        except AuthorizationAssignmentLoadError as exc:
            issues.extend(
                AuthorizationAssignmentIssue(f"{path.name}:{item.key}", item.message)
                for item in exc.issues
            )
            continue
        prior = seen.get(assignment.assignment_id)
        if prior is not None:
            issues.append(
                AuthorizationAssignmentIssue(
                    path.name,
                    f"duplicate authorization assignment id {assignment.assignment_id!r} "
                    f"(also in {prior})",
                )
            )
            continue
        seen[assignment.assignment_id] = path.name
        unknown_capabilities = assignment.capabilities - known_capability_ids
        unknown_profiles = assignment.execution_profiles - known_execution_profiles
        if unknown_capabilities:
            issues.append(
                AuthorizationAssignmentIssue(
                    f"{path.name}:capabilities",
                    f"unknown capability ids: {sorted(unknown_capabilities)}",
                )
            )
        if unknown_profiles:
            issues.append(
                AuthorizationAssignmentIssue(
                    f"{path.name}:execution_profiles",
                    f"unknown execution profiles: {sorted(unknown_profiles)}",
                )
            )
        if not unknown_capabilities and not unknown_profiles:
            loaded.append(assignment)
    if issues:
        raise AuthorizationAssignmentLoadError(issues)
    return tuple(loaded)


__all__ = [
    "AuthorizationAssignmentIssue",
    "AuthorizationAssignmentLoadError",
    "AuthorizationConstraints",
    "AuthorizationEnforcement",
    "AuthorizationPolicyAssignment",
    "AuthorizationPosture",
    "AuthorizationScopeLevel",
    "GrantMode",
    "load_authorization_assignment_from_mapping",
    "load_authorization_assignment_catalog",
]
