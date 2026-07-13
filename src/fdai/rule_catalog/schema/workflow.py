"""Workflow catalog loader - reads YAML instances from
``rule-catalog/workflows/`` and validates each against the ``workflow``
JSON Schema plus the :class:`Workflow` pydantic model, then cross-references
every step against the ActionType (and optionally the rule) catalog.
Aggregates every issue in a single :class:`WorkflowCatalogError`.

Placement rationale mirrors :mod:`fdai.rule_catalog.schema.action_type`
and :mod:`fdai.rule_catalog.schema.object_type`: this module is pure I/O
plus validation, so the entry point and any fork extension consume the
loaded tuple without re-parsing YAML.

Why this exists
---------------
A Workflow declares a business process as an ordered list of steps, each
referencing one ontology ActionType (see
[process-automation.md](../../../../docs/roadmap/decisioning/process-automation.md)).
The business-critical linkage - a step to its ActionType - is a name
cross-reference resolved here, exactly as a Rule's ``remediates`` resolves
to an ActionType in :mod:`fdai.rule_catalog.schema.rule`. A typo fails at
load, not at first dispatch.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from fdai.shared.contracts.models import Workflow, WorkflowStepKind
from fdai.shared.contracts.registry import SchemaRegistry

_WORKFLOW_SCHEMA_NAME = "workflow"


@dataclass(frozen=True, slots=True)
class WorkflowIssue:
    key: str
    message: str


class WorkflowCatalogError(ValueError):
    """Aggregate error surfaced when loading a Workflow YAML fails."""

    def __init__(self, issues: list[WorkflowIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{i.key}: {i.message}" for i in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"workflow catalog validation failed: {preview}{suffix}")


def _yaml_load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _cross_reference_issues(
    workflow: Workflow,
    *,
    origin: str,
    action_type_names: set[str],
    rule_ids: set[str] | None,
) -> list[WorkflowIssue]:
    """Resolve every step reference against the supplied catalogs.

    ``action_type_ref`` and ``compensated_by`` MUST name a registered
    ActionType. ``guard_rule_ref`` MUST name a registered Rule id, but
    only when ``rule_ids`` is supplied - a caller that has not loaded the
    rule catalog (unit tests, early boot) passes ``None`` to skip that
    cross-check rather than fail spuriously.
    """
    issues: list[WorkflowIssue] = []
    for step in workflow.steps:
        if (
            step.kind is WorkflowStepKind.ACTION
            and step.action_type_ref not in action_type_names
        ):
            issues.append(
                WorkflowIssue(
                    key=f"{origin}:steps.{step.id}.action_type_ref",
                    message=(
                        f"unknown ActionType {step.action_type_ref!r} "
                        "(not registered in rule-catalog/action-types/)"
                    ),
                )
            )
        if step.compensated_by is not None and step.compensated_by not in action_type_names:
            issues.append(
                WorkflowIssue(
                    key=f"{origin}:steps.{step.id}.compensated_by",
                    message=(
                        f"unknown ActionType {step.compensated_by!r} "
                        "(not registered in rule-catalog/action-types/)"
                    ),
                )
            )
        if (
            rule_ids is not None
            and step.guard_rule_ref is not None
            and step.guard_rule_ref not in rule_ids
        ):
            issues.append(
                WorkflowIssue(
                    key=f"{origin}:steps.{step.id}.guard_rule_ref",
                    message=(
                        f"unknown Rule {step.guard_rule_ref!r} "
                        "(not registered in rule-catalog/catalog/)"
                    ),
                )
            )
    return issues


def load_workflow_from_mapping(
    raw: Mapping[str, Any],
    *,
    schema_registry: SchemaRegistry,
    action_type_names: set[str],
    rule_ids: set[str] | None = None,
    origin: str = "<mapping>",
) -> Workflow:
    """Validate a single Workflow mapping and return the pydantic model.

    Aggregates JSON Schema violations, pydantic errors (including the
    structural invariants: unique step ids, resolvable ``on_failure``),
    and catalog cross-reference misses under one
    :class:`WorkflowCatalogError`. The cross-reference sets MUST be
    supplied - this function does NOT read the ActionType or rule catalog
    itself so tests can inject stubs.
    """
    issues: list[WorkflowIssue] = []

    schema = schema_registry.get(_WORKFLOW_SCHEMA_NAME)
    validator = Draft202012Validator(dict(schema))
    for err in sorted(validator.iter_errors(dict(raw)), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in err.absolute_path) or "<root>"
        issues.append(WorkflowIssue(key=f"{origin}:{path}", message=err.message))

    if issues:
        raise WorkflowCatalogError(issues)

    try:
        model = Workflow.model_validate(raw)
    except ValueError as exc:
        errors = getattr(exc, "errors", None)
        if callable(errors):
            for e in errors():
                loc = ".".join(str(p) for p in e.get("loc", ()))
                issues.append(WorkflowIssue(key=f"{origin}:{loc}", message=e["msg"]))
        else:
            issues.append(WorkflowIssue(key=f"{origin}:<root>", message=str(exc)))
        raise WorkflowCatalogError(issues) from exc

    xref = _cross_reference_issues(
        model,
        origin=origin,
        action_type_names=action_type_names,
        rule_ids=rule_ids,
    )
    if xref:
        raise WorkflowCatalogError(xref)

    return model


def _iter_yaml_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.glob("*.yaml")):
        if path.name == "README.md":
            continue
        yield path


def load_workflow_catalog(
    root: Path,
    *,
    schema_registry: SchemaRegistry,
    action_type_names: set[str],
    rule_ids: set[str] | None = None,
) -> tuple[Workflow, ...]:
    """Load every Workflow YAML under ``root`` (non-recursive), fail-closed.

    Aggregates every issue in every file into a single
    :class:`WorkflowCatalogError`. Duplicate ``name`` across files is a
    hard error - the audit key MUST be globally unique across upstream and
    every fork addition.
    """
    aggregated: list[WorkflowIssue] = []
    loaded: list[Workflow] = []
    seen_names: dict[str, str] = {}

    for path in _iter_yaml_files(root):
        try:
            raw = _yaml_load(path)
        except yaml.YAMLError as exc:
            aggregated.append(WorkflowIssue(key=path.name, message=f"invalid YAML: {exc}"))
            continue

        if not isinstance(raw, Mapping):
            aggregated.append(
                WorkflowIssue(key=path.name, message="workflow top-level must be a mapping")
            )
            continue

        try:
            model = load_workflow_from_mapping(
                raw,
                schema_registry=schema_registry,
                action_type_names=action_type_names,
                rule_ids=rule_ids,
                origin=path.name,
            )
        except WorkflowCatalogError as exc:
            aggregated.extend(exc.issues)
            continue

        prior = seen_names.get(model.name)
        if prior is not None:
            aggregated.append(
                WorkflowIssue(
                    key=path.name,
                    message=(
                        f"duplicate Workflow name {model.name!r} (already declared in {prior})"
                    ),
                )
            )
            continue
        seen_names[model.name] = path.name
        loaded.append(model)

    if aggregated:
        raise WorkflowCatalogError(aggregated)

    return tuple(loaded)


def workflow_names(catalog: Iterable[Workflow]) -> set[str]:
    """Return the set of Workflow ``name`` values in ``catalog``."""
    return {w.name for w in catalog}


__all__ = [
    "WorkflowCatalogError",
    "WorkflowIssue",
    "load_workflow_catalog",
    "load_workflow_from_mapping",
    "workflow_names",
]
