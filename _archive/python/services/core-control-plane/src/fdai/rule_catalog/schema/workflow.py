"""Workflow catalog file loader.

The pure Workflow model and mapping validator live in
``fdai_service_contracts.workflow_catalog`` so Core and the independent
Operator service use the same implementation. This Core module keeps the
catalog file I/O and startup fail-closed aggregation behavior.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml
from fdai_service_contracts.workflow_catalog import (
    SignalTypeRegistry,
    Workflow,
    WorkflowCatalogError,
    WorkflowIssue,
    WorkflowTriggerEventRegistry,
    load_workflow_from_mapping,
    workflow_names,
    workflow_to_yaml,
)

from fdai.rule_catalog.schema.signal_type import load_signal_type_registry_from_mapping
from fdai.rule_catalog.schema.workflow_trigger_event import (
    load_workflow_trigger_event_registry_from_mapping,
)
from fdai.shared.contracts.registry import SchemaRegistry


def _yaml_load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


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
    if not isinstance(raw, dict):
        raise WorkflowCatalogError(
            [WorkflowIssue(key=str(path), message="signal-type top-level must be a mapping")]
        )
    return load_signal_type_registry_from_mapping(raw)


def _load_default_workflow_trigger_events(root: Path) -> WorkflowTriggerEventRegistry | None:
    path = root.parent / "vocabulary" / "workflow-trigger-events.yaml"
    if not path.is_file():
        return None
    raw = _yaml_load(path)
    if not isinstance(raw, dict):
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
    """Load every Workflow YAML under ``root`` (non-recursive), fail-closed."""

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

        if not isinstance(raw, dict):
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


__all__ = [
    "WorkflowCatalogError",
    "WorkflowIssue",
    "load_workflow_catalog",
    "load_workflow_from_mapping",
    "workflow_names",
    "workflow_to_yaml",
]
