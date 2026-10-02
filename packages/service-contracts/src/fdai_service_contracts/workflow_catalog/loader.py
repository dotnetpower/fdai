"""Pure Workflow mapping loader shared by Core and Operator."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from fdai_service_contracts.schema import SchemaRegistry
from fdai_service_contracts.workflow_catalog.enums import (
    WorkflowStepKind,
    WorkflowTriggerKind,
    WorkflowTriggerSignalReferenceKind,
)
from fdai_service_contracts.workflow_catalog.models import Workflow
from fdai_service_contracts.workflow_catalog.signal_type import SignalTypeRegistry
from fdai_service_contracts.workflow_catalog.workflow_trigger_event import (
    WorkflowTriggerEventRegistry,
)

_WORKFLOW_SCHEMA_NAME = "workflow"


@dataclass(frozen=True, slots=True)
class WorkflowIssue:
    key: str
    message: str


class WorkflowCatalogError(ValueError):
    """Aggregate error surfaced when loading a Workflow mapping fails."""

    def __init__(self, issues: list[WorkflowIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{i.key}: {i.message}" for i in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"workflow catalog validation failed: {preview}{suffix}")


def _cross_reference_issues(
    workflow: Workflow,
    *,
    origin: str,
    action_type_names: set[str],
    rule_ids: set[str] | None,
    signal_types: SignalTypeRegistry | None,
    workflow_trigger_events: WorkflowTriggerEventRegistry | None,
) -> list[WorkflowIssue]:
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
    """Validate a single Workflow mapping and return the pydantic model."""

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


def workflow_to_yaml(workflow: Workflow) -> str:
    """Return the canonical YAML preview used by workflow validation."""

    return yaml.safe_dump(
        workflow.model_dump(mode="json", exclude_none=True),
        sort_keys=False,
        allow_unicode=True,
    )


def workflow_names(catalog: Iterable[Workflow]) -> set[str]:
    """Return the set of Workflow ``name`` values in ``catalog``."""

    return {w.name for w in catalog}


__all__ = [
    "WorkflowCatalogError",
    "WorkflowIssue",
    "load_workflow_from_mapping",
    "workflow_names",
    "workflow_to_yaml",
]
