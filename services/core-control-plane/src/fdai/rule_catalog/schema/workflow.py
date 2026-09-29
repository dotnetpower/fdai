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

from fdai.rule_catalog.schema.signal_type import (
    SignalTypeRegistry,
    load_signal_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.workflow_trigger_event import (
    WorkflowTriggerEventRegistry,
    load_workflow_trigger_event_registry_from_mapping,
)
from fdai.shared.contracts.models import (
    Workflow,
    WorkflowStepKind,
    WorkflowTriggerKind,
    WorkflowTriggerSignalReferenceKind,
)
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
    signal_types: SignalTypeRegistry | None,
    workflow_trigger_events: WorkflowTriggerEventRegistry | None,
) -> list[WorkflowIssue]:
    """Resolve every step reference against the supplied catalogs.

    ``action_type_ref`` and ``compensated_by`` MUST name a registered
    ActionType. ``guard_rule_ref`` MUST name a registered Rule id, but
    only when ``rule_ids`` is supplied - a caller that has not loaded the
    rule catalog (unit tests, early boot) passes ``None`` to skip that
    cross-check rather than fail spuriously.
    """
    issues: list[WorkflowIssue] = []
    if (
        workflow.trigger.kind is WorkflowTriggerKind.SIGNAL
        and workflow.trigger.signal_type is not None
    ):
        signal_id_matches = (
            {workflow.trigger.signal_type} & signal_types.ids()
            if signal_types is not None
            else frozenset()
        )
        signal_matches = (
            signal_types.resolve_declared(workflow.trigger.signal_type)
            if signal_types is not None
            else frozenset()
        )
        workflow_trigger_matches = (
            workflow_trigger_events.ids() & {workflow.trigger.signal_type}
            if workflow_trigger_events is not None
            else frozenset()
        )
        counted_signal_matches = signal_id_matches or (
            frozenset() if workflow_trigger_matches else signal_matches
        )
        match_count = len(counted_signal_matches) + len(workflow_trigger_matches)
        if match_count == 0 and (signal_types is not None or workflow_trigger_events is not None):
            issues.append(
                WorkflowIssue(
                    key=f"{origin}:trigger.signal_type",
                    message=(
                        f"unknown workflow trigger signal_type {workflow.trigger.signal_type!r} "
                        "(not registered in SignalType or workflow-trigger-events vocabularies)"
                    ),
                )
            )
        elif match_count > 1:
            issues.append(
                WorkflowIssue(
                    key=f"{origin}:trigger.signal_type",
                    message=(
                        f"ambiguous workflow trigger signal_type {workflow.trigger.signal_type!r} "
                        "resolved in more than one trigger vocabulary"
                    ),
                )
            )
    for step in workflow.steps:
        if step.kind is WorkflowStepKind.ACTION and step.action_type_ref not in action_type_names:
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
    signal_types: SignalTypeRegistry | None = None,
    workflow_trigger_events: WorkflowTriggerEventRegistry | None = None,
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
        signal_types=signal_types,
        workflow_trigger_events=workflow_trigger_events,
    )
    if xref:
        raise WorkflowCatalogError(xref)

    if (
        model.trigger.kind is WorkflowTriggerKind.SIGNAL
        and model.trigger.signal_type is not None
        and model.trigger.signal_reference_kind is None
    ):
        signal_matches = (
            signal_types.resolve_declared(model.trigger.signal_type)
            if signal_types is not None
            else frozenset()
        )
        workflow_trigger_matches = (
            workflow_trigger_events.ids() & {model.trigger.signal_type}
            if workflow_trigger_events is not None
            else frozenset()
        )
        if signal_matches and not workflow_trigger_matches:
            model = model.model_copy(
                update={
                    "trigger": model.trigger.model_copy(
                        update={
                            "signal_reference_kind": (
                                WorkflowTriggerSignalReferenceKind.SIGNAL_TYPE
                            )
                        }
                    )
                }
            )
        elif workflow_trigger_matches:
            model = model.model_copy(
                update={
                    "trigger": model.trigger.model_copy(
                        update={
                            "signal_reference_kind": (
                                WorkflowTriggerSignalReferenceKind.WORKFLOW_TRIGGER_EVENT
                            )
                        }
                    )
                }
            )

    return model


def _iter_yaml_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.glob("*.yaml")):
        if path.name == "README.md":
            continue
        yield path


def _load_default_signal_types(root: Path) -> SignalTypeRegistry | None:
    path = root.parent / "vocabulary" / "signal-types.yaml"
    if not path.is_file():
        return None
    raw = _yaml_load(path)
    if not isinstance(raw, Mapping):
        raise WorkflowCatalogError(
            [WorkflowIssue(key=str(path), message="signal-type top-level must be a mapping")]
        )
    return load_signal_type_registry_from_mapping(raw)


def _load_default_workflow_trigger_events(root: Path) -> WorkflowTriggerEventRegistry | None:
    path = root.parent / "vocabulary" / "workflow-trigger-events.yaml"
    if not path.is_file():
        return None
    raw = _yaml_load(path)
    if not isinstance(raw, Mapping):
        raise WorkflowCatalogError(
            [
                WorkflowIssue(
                    key=str(path),
                    message="workflow-trigger-event top-level must be a mapping",
                )
            ]
        )
    return load_workflow_trigger_event_registry_from_mapping(raw)


def load_workflow_catalog(
    root: Path,
    *,
    schema_registry: SchemaRegistry,
    action_type_names: set[str],
    rule_ids: set[str] | None = None,
    signal_types: SignalTypeRegistry | None = None,
    workflow_trigger_events: WorkflowTriggerEventRegistry | None = None,
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
    if signal_types is None:
        signal_types = _load_default_signal_types(root)
    if workflow_trigger_events is None:
        workflow_trigger_events = _load_default_workflow_trigger_events(root)

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
                signal_types=signal_types,
                workflow_trigger_events=workflow_trigger_events,
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
