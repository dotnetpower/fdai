"""Catalog-as-code loader for governance assignments.

Validates a raw assignment mapping (parsed from a YAML catalog file) against
``assignment.schema.json`` and builds a
:class:`~fdai.rule_catalog.schema.assignment.Assignment`. Mirrors the exemption
loader's fail-at-the-boundary contract: all schema issues are collected and
raised together, so a malformed catalog entry surfaces every problem at once
rather than one at a time.

Pure and I/O-free at the mapping boundary (the caller reads the YAML file and
passes the dict); the JSON Schema ships as a package resource.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

from fdai.rule_catalog.schema.assignment import Assignment
from fdai.rule_catalog.schema.effect import Effect, Enforcement
from fdai.rule_catalog.schema.provenance import Provenance
from fdai.rule_catalog.schema.rule_set import (
    RuleSet,
    RuleSetMember,
    assignment_from_rule_set,
)
from fdai.rule_catalog.schema.scope import Scope, ScopeLevel, ScopeSelector

_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_ASSIGNMENT_SCHEMA_FILE = "assignment.schema.json"
_RULE_SET_SCHEMA_FILE = "rule_set.schema.json"

# The catalog YAML uses hyphenated level labels; the domain enum is an IntEnum
# (ordered for precedence) with no string value, so the loader owns the mapping.
_LEVEL_BY_LABEL: dict[str, ScopeLevel] = {
    "organization": ScopeLevel.ORGANIZATION,
    "account": ScopeLevel.ACCOUNT,
    "resource-group": ScopeLevel.RESOURCE_GROUP,
    "resource": ScopeLevel.RESOURCE,
}


@dataclass(frozen=True, slots=True)
class GovernanceLoadIssue:
    key: str
    message: str


class GovernanceLoadError(ValueError):
    """Aggregate error surfaced at the governance-assignment load boundary."""

    def __init__(self, issues: list[GovernanceLoadIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{i.key}: {i.message}" for i in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"governance assignment validation failed: {preview}{suffix}")


def _load_schema(name: str) -> dict[str, Any]:
    raw = resources.files(_SCHEMA_PACKAGE).joinpath(name).read_text(encoding="utf-8")
    return json.loads(raw)  # type: ignore[no-any-return]


_ASSIGNMENT_VALIDATOR = Draft202012Validator(_load_schema(_ASSIGNMENT_SCHEMA_FILE))
_RULE_SET_VALIDATOR = Draft202012Validator(_load_schema(_RULE_SET_SCHEMA_FILE))


def _collect_issues(
    validator: Draft202012Validator, raw: Mapping[str, Any]
) -> list[GovernanceLoadIssue]:
    return [
        GovernanceLoadIssue(
            key="/".join(str(p) for p in err.path) or "<root>",
            message=err.message,
        )
        for err in sorted(validator.iter_errors(raw), key=lambda e: list(e.path))
    ]


def _build_scope(raw: Mapping[str, Any]) -> Scope:
    selector: ScopeSelector | None = None
    sel_raw = raw.get("selector")
    if sel_raw is not None:
        selector = ScopeSelector(
            resource_types=frozenset(sel_raw.get("resource_types", ())),
            tags=dict(sel_raw.get("tags", {})),
            resource_ids=frozenset(sel_raw.get("resource_ids", ())),
        )
    return Scope(
        level=_LEVEL_BY_LABEL[raw["level"]],
        id=raw["id"],
        selector=selector,
        excludes=frozenset(raw.get("excludes", ())),
    )


def _build_provenance(raw: Mapping[str, Any]) -> Provenance | None:
    prov_raw = raw.get("provenance")
    if prov_raw is None:
        return None
    try:
        return Provenance.from_mapping(prov_raw)
    except ValueError as exc:
        raise GovernanceLoadError(
            [GovernanceLoadIssue(key="provenance", message=str(exc))]
        ) from exc


def load_assignment_from_mapping(
    raw: Mapping[str, Any],
    *,
    rule_sets: Mapping[str, RuleSet] | None = None,
) -> Assignment:
    """Validate ``raw`` against the assignment schema and build an Assignment.

    An assignment binds either an explicit ``target_rule_ids`` list or a
    ``rule_set`` (by id) to a scope. When it references a rule-set, ``rule_sets``
    MUST supply that set; the rule-set's per-rule ``default_effect`` becomes the
    assignment's ``effect_overrides`` (any explicit ``effect_overrides`` in the
    mapping tune it further), via
    :func:`~fdai.rule_catalog.schema.rule_set.assignment_from_rule_set`.

    Raises :class:`GovernanceLoadError` carrying every schema issue on failure -
    including an unresolved ``rule_set`` reference; on success returns the domain
    :class:`Assignment` (whose own constructor enforces the non-empty-id /
    at-least-one-rule invariants).
    """
    issues = _collect_issues(_ASSIGNMENT_VALIDATOR, raw)
    if issues:
        raise GovernanceLoadError(issues)

    overrides = {k: Effect(v) for k, v in raw.get("effect_overrides", {}).items()}
    effect = Effect(raw.get("effect", "audit"))
    enforcement = Enforcement(raw.get("enforcement", "do-not-enforce"))
    parameters = dict(raw.get("parameters", {}))
    scope = _build_scope(raw["scope"])
    provenance = _build_provenance(raw)

    rule_set_ref = raw.get("rule_set")
    if rule_set_ref is not None:
        available = rule_sets or {}
        rule_set = available.get(rule_set_ref)
        if rule_set is None:
            raise GovernanceLoadError(
                [
                    GovernanceLoadIssue(
                        key="rule_set",
                        message=f"references unknown rule-set {rule_set_ref!r}",
                    )
                ]
            )
        return assignment_from_rule_set(
            rule_set,
            id=raw["id"],
            scope=scope,
            effect=effect,
            enforcement=enforcement,
            parameters=parameters,
            extra_overrides=overrides,
            provenance=provenance,
        )

    return Assignment(
        id=raw["id"],
        target_rule_ids=frozenset(raw["target_rule_ids"]),
        scope=scope,
        effect=effect,
        enforcement=enforcement,
        parameters=parameters,
        effect_overrides=overrides,
        provenance=provenance,
    )


def load_rule_set_from_mapping(raw: Mapping[str, Any]) -> RuleSet:
    """Validate ``raw`` against the rule-set schema and build a RuleSet.

    Raises :class:`GovernanceLoadError` carrying every schema issue on failure;
    on success returns the domain :class:`RuleSet` (whose constructor enforces
    the non-empty / no-duplicate-member invariants).
    """
    issues = _collect_issues(_RULE_SET_VALIDATOR, raw)
    if issues:
        raise GovernanceLoadError(issues)

    members = tuple(
        RuleSetMember(
            rule_id=m["rule_id"],
            version=m["version"],
            default_effect=Effect(m.get("default_effect", "audit")),
        )
        for m in raw["members"]
    )
    return RuleSet(
        id=raw["id"],
        version=raw["version"],
        members=members,
        provenance=_build_provenance(raw),
    )


__all__ = [
    "GovernanceLoadError",
    "GovernanceLoadIssue",
    "load_assignment_from_mapping",
    "load_rule_set_from_mapping",
]
