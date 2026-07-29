"""Rule catalog loader - reads normalized `Rule` YAMLs from
``rule-catalog/catalog/`` and validates each against the shipped
``rule/1.0.0`` JSON Schema, the :class:`Rule` pydantic model, and the
cross-references required by the ontology dispatch layer.

Cross-references (fail-closed):

- ``remediates`` MUST resolve to a registered ActionType ``name`` from
  :func:`fdai.rule_catalog.schema.action_type.load_action_type_catalog`.
- Every entry in ``alternatives`` MUST resolve the same way.
- ``resource_type`` MUST exist in the canonical CSP-neutral vocabulary
  loaded via :func:`load_resource_type_registry_from_mapping` from
  :mod:`fdai.rule_catalog.schema.resource_type`.
- Duplicate ``id`` across files is a hard error.

Every issue across every file is aggregated into a single
:class:`RuleCatalogError` so a reviewer sees the whole diff, not the
first surprise.

Design notes
------------
The loader is pure I/O + validation; it does NOT compile Rego, evaluate
policy, or touch the graph. The T0 engine consumes the loaded tuple and
builds its lookup indexes (see
``src/fdai/core/tiers/t0_deterministic/``).

Placement rationale: this module lives next to the other schema loaders
(``action_type.py``, ``resource_type.py``, ``exemption.py``) because it
enforces the *catalog* invariants; the T0 engine layer stays free of
YAML plumbing.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry
from fdai.shared.contracts.models import (
    OntologyActionType,
    Rule,
    SubmissionCriterionKind,
)
from fdai.shared.contracts.registry import SchemaRegistry

_RULE_SCHEMA_NAME = "rule"


@dataclass(frozen=True, slots=True)
class RuleIssue:
    key: str
    message: str


class RuleCatalogError(ValueError):
    """Aggregate error surfaced when loading a rule catalog fails."""

    def __init__(self, issues: list[RuleIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{i.key}: {i.message}" for i in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"rule catalog validation failed: {preview}{suffix}")


def _yaml_load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _cross_reference_issues(
    rule: Rule,
    *,
    origin: str,
    action_type_names: set[str],
    resource_type_ids: set[str],
    policies_root: Path | None,
    remediation_root: Path | None,
) -> list[RuleIssue]:
    issues: list[RuleIssue] = []

    if rule.resource_type not in resource_type_ids:
        issues.append(
            RuleIssue(
                key=f"{origin}:resource_type",
                message=(
                    f"unknown resource_type {rule.resource_type!r} "
                    "(not in rule-catalog/vocabulary/resource-types.yaml)"
                ),
            )
        )

    for idx, resource_type in enumerate(rule.applies_to):
        if resource_type not in resource_type_ids:
            issues.append(
                RuleIssue(
                    key=f"{origin}:applies_to[{idx}]",
                    message=f"unknown applies_to resource type {resource_type!r}",
                )
            )
    if rule.resource_type not in rule.applies_to:
        issues.append(
            RuleIssue(
                key=f"{origin}:applies_to",
                message=(f"applies_to MUST contain canonical resource_type {rule.resource_type!r}"),
            )
        )

    for idx, criterion in enumerate(rule.submission_criteria):
        if (
            criterion.kind is SubmissionCriterionKind.RESOURCE_TYPE_REGISTERED
            and criterion.value not in resource_type_ids
        ):
            issues.append(
                RuleIssue(
                    key=f"{origin}:submission_criteria[{idx}]",
                    message=f"unknown registered resource type {criterion.value!r}",
                )
            )

    if rule.remediates not in action_type_names:
        issues.append(
            RuleIssue(
                key=f"{origin}:remediates",
                message=(
                    f"unknown ActionType {rule.remediates!r} "
                    "(not registered in rule-catalog/action-types/)"
                ),
            )
        )

    for idx, alt in enumerate(rule.alternatives):
        if alt not in action_type_names:
            issues.append(
                RuleIssue(
                    key=f"{origin}:alternatives[{idx}]",
                    message=(
                        f"unknown ActionType {alt!r} (not registered in rule-catalog/action-types/)"
                    ),
                )
            )

    if policies_root is not None:
        policy_issue = _check_policy_reference(rule, origin, policies_root)
        if policy_issue is not None:
            issues.append(policy_issue)

    if remediation_root is not None:
        remediation_issue = _check_remediation_template(rule, origin, remediation_root)
        if remediation_issue is not None:
            issues.append(remediation_issue)

    return issues


def _check_policy_reference(
    rule: Rule,
    origin: str,
    policies_root: Path,
) -> RuleIssue | None:
    """Verify a rule's ``check_logic.reference`` points at an existing Rego file.

    Only checks references that start with ``policies/`` (our convention);
    inline expressions and other reference shapes are left to the runner.
    ``check_logic.kind == "expression"`` short-circuits - an expression is
    not a file path by definition.
    """
    from fdai.shared.contracts.models import CheckLogicKind

    if rule.check_logic.kind is not CheckLogicKind.REGO:
        return None

    reference = rule.check_logic.reference
    if not reference.startswith("policies/"):
        return None

    relative = reference[len("policies/") :]
    # Defend against absolute paths and traversal (`..`); a rule that
    # tries either is a hard schema break, not a "resolve harder" case.
    rel_path = Path(relative)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        return RuleIssue(
            key=f"{origin}:check_logic.reference",
            message=f"policy reference {reference!r} MUST be a repo-relative path without '..'",
        )

    target = policies_root / rel_path
    if not target.is_file():
        return RuleIssue(
            key=f"{origin}:check_logic.reference",
            message=(f"policy file not found: {reference!r} (expected at {target.as_posix()!r})"),
        )
    return None


def _check_remediation_template(
    rule: Rule,
    origin: str,
    remediation_root: Path,
) -> RuleIssue | None:
    """Verify a rule's ``remediation.template_ref`` points at an existing template.

    Only checks refs that start with ``remediation/`` (our convention); other
    shapes (opaque ids, package URIs) pass through untouched so a future
    non-file transport is additive.
    """
    reference = rule.remediation.template_ref
    if not reference.startswith("remediation/"):
        return None

    relative = reference[len("remediation/") :]
    rel_path = Path(relative)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        return RuleIssue(
            key=f"{origin}:remediation.template_ref",
            message=(
                f"remediation template ref {reference!r} MUST be a repo-relative path without '..'"
            ),
        )

    target = remediation_root / rel_path
    if not target.is_file():
        return RuleIssue(
            key=f"{origin}:remediation.template_ref",
            message=(
                f"remediation template file not found: {reference!r} "
                f"(expected at {target.as_posix()!r})"
            ),
        )
    return None


def load_rule_from_mapping(
    raw: Mapping[str, Any],
    *,
    schema_registry: SchemaRegistry,
    action_type_names: set[str],
    resource_type_ids: set[str],
    origin: str = "<mapping>",
    policies_root: Path | None = None,
    remediation_root: Path | None = None,
) -> Rule:
    """Validate a single rule mapping and return the pydantic :class:`Rule`.

    Fails closed with a :class:`RuleCatalogError` that aggregates JSON
    Schema violations, pydantic issues, and cross-reference misses. The
    cross-reference sets MUST be supplied - this function does NOT read
    the ActionType or ResourceType catalogs itself; that is the caller's
    (composition-time) responsibility, so tests can inject stubs.

    ``policies_root`` is optional; when provided, ``check_logic.reference``
    values that start with ``policies/`` are resolved against it and the
    Rego file MUST exist on disk (fail-closed). Pass ``None`` to skip the
    filesystem check (e.g. when the caller ships policies through a
    different distribution channel).

    ``remediation_root`` follows the same optional pattern for
    ``remediation.template_ref`` - refs prefixed with ``remediation/``
    MUST resolve to an on-disk template file when the root is provided.
    """
    issues: list[RuleIssue] = []

    schema = schema_registry.get(_RULE_SCHEMA_NAME)
    validator = Draft202012Validator(dict(schema))
    for err in sorted(validator.iter_errors(dict(raw)), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in err.absolute_path) or "<root>"
        issues.append(RuleIssue(key=f"{origin}:{path}", message=err.message))

    if issues:
        raise RuleCatalogError(issues)

    try:
        model = Rule.model_validate(raw)
    except ValueError as exc:
        errors = getattr(exc, "errors", None)
        if callable(errors):
            for e in errors():
                loc = ".".join(str(p) for p in e.get("loc", ()))
                issues.append(RuleIssue(key=f"{origin}:{loc}", message=e["msg"]))
        else:
            issues.append(RuleIssue(key=f"{origin}:<root>", message=str(exc)))
        raise RuleCatalogError(issues) from exc

    if model.schema_version != "2.0.0":
        raise RuleCatalogError(
            [
                RuleIssue(
                    key=f"{origin}:schema_version",
                    message="runtime rule catalog requires schema_version 2.0.0",
                )
            ]
        )

    xref_issues = _cross_reference_issues(
        model,
        origin=origin,
        action_type_names=action_type_names,
        resource_type_ids=resource_type_ids,
        policies_root=policies_root,
        remediation_root=remediation_root,
    )
    if xref_issues:
        raise RuleCatalogError(xref_issues)

    return model


def _iter_yaml_files(root: Path) -> Iterator[Path]:
    yield from sorted(root.glob("*.yaml"))


def load_rule_catalog(
    root: Path,
    *,
    schema_registry: SchemaRegistry,
    action_types: Iterable[OntologyActionType],
    resource_types: ResourceTypeRegistry,
    policies_root: Path | None = None,
    remediation_root: Path | None = None,
) -> tuple[Rule, ...]:
    """Load every rule YAML under ``root`` (non-recursive), fail-closed.

    Aggregates every issue in every file into a single
    :class:`RuleCatalogError`. Duplicate ``id`` across files is a hard
    error; consistent with the ontology dispatch (M:1 remediates, unique
    rule id) the loader does NOT silently merge same-id entries.

    ``policies_root`` - when provided, every rule's ``check_logic.reference``
    that starts with ``policies/`` MUST resolve to a file that exists
    under ``policies_root``. Missing files fail the load; the check is
    skipped when ``policies_root`` is ``None`` (e.g. tests that stub the
    policy filesystem).

    ``remediation_root`` - same optional pattern for
    ``remediation.template_ref`` values that start with ``remediation/``.
    """
    action_type_names = {a.name for a in action_types}
    resource_type_ids = resource_types.ids()

    aggregated: list[RuleIssue] = []
    loaded: list[Rule] = []
    seen_ids: dict[str, str] = {}

    for path in _iter_yaml_files(root):
        try:
            raw = _yaml_load(path)
        except yaml.YAMLError as exc:
            aggregated.append(RuleIssue(key=path.name, message=f"invalid YAML: {exc}"))
            continue
        if not isinstance(raw, Mapping):
            aggregated.append(RuleIssue(key=path.name, message="top-level must be a mapping"))
            continue
        try:
            model = load_rule_from_mapping(
                raw,
                schema_registry=schema_registry,
                action_type_names=action_type_names,
                resource_type_ids=resource_type_ids,
                origin=path.name,
                policies_root=policies_root,
                remediation_root=remediation_root,
            )
        except RuleCatalogError as exc:
            aggregated.extend(exc.issues)
            continue

        prior = seen_ids.get(model.id)
        if prior is not None:
            aggregated.append(
                RuleIssue(
                    key=path.name,
                    message=f"duplicate rule id {model.id!r} (also in {prior})",
                )
            )
            continue
        seen_ids[model.id] = path.name
        loaded.append(model)

    if aggregated:
        raise RuleCatalogError(aggregated)

    return tuple(loaded)


__all__ = [
    "RuleCatalogError",
    "RuleIssue",
    "load_rule_catalog",
    "load_rule_from_mapping",
]
