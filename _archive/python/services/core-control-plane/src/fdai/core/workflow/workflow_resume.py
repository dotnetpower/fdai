"""Audit-safe workflow resume envelope construction and validation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from fdai.rule_catalog.schema.action_type import argument_schema_redaction_paths
from fdai.shared.contracts.models import Mode, OntologyActionType, Workflow, WorkflowStepKind
from fdai.shared.providers.process_runtime import ProcessEvent, ProcessSnapshot

_CONTEXT_TOKEN = re.compile(r"\$\{([a-z0-9_.]+)\}")


class WorkflowResumeError(RuntimeError):
    """A Process cannot be resumed from exact durable evidence."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True, slots=True)
class WorkflowResumeEnvelope:
    """Server-owned inputs needed to reproduce one Process run."""

    process_id: str
    workflow_ref: str
    workflow_version: str
    target_resource_id: str
    correlation_id: str
    trigger_ts: datetime
    mode: Mode
    context: Mapping[str, str]


def build_resume_payload(
    *,
    workflow: Workflow,
    action_types: Mapping[str, OntologyActionType],
    trigger_ts: datetime,
    mode: Mode,
    context: Mapping[str, str],
) -> dict[str, object]:
    """Return the minimal audit-safe context needed for exact resume."""
    referenced: set[str] = set()
    redacted: set[str] = set()
    if "requester.principal" in context:
        referenced.add("requester.principal")
    for step in workflow.steps:
        action_type = (
            action_types.get(step.action_type_ref or "")
            if step.kind is WorkflowStepKind.ACTION
            else None
        )
        redaction_paths = (
            argument_schema_redaction_paths(action_type) if action_type is not None else frozenset()
        )
        for param_name, value in step.params.items():
            if not isinstance(value, str):
                continue
            tokens = set(_CONTEXT_TOKEN.findall(value))
            if param_name in redaction_paths:
                redacted.update(tokens & context.keys())
            else:
                referenced.update(tokens & context.keys())
    referenced.difference_update(redacted)
    return {
        "trigger_ts": trigger_ts.isoformat(),
        "mode": mode.value,
        "context": {key: context[key] for key in sorted(referenced)},
        "context_complete": not redacted,
    }


def load_resume_envelope(
    *,
    workflow: Workflow,
    snapshot: ProcessSnapshot,
    created_event: ProcessEvent,
) -> WorkflowResumeEnvelope:
    """Validate and return exact resume inputs from a Process creation event."""
    payload = created_event.payload.get("resume")
    if not isinstance(payload, Mapping):
        raise WorkflowResumeError(
            "resume_evidence_unavailable",
            "Process predates durable workflow resume evidence",
        )
    if payload.get("context_complete") is not True:
        raise WorkflowResumeError(
            "resume_context_redacted",
            "Process resume context contains a redacted workflow argument",
        )
    trigger_raw = payload.get("trigger_ts")
    mode_raw = payload.get("mode")
    context_raw = payload.get("context")
    if not isinstance(trigger_raw, str) or not isinstance(mode_raw, str):
        raise WorkflowResumeError(
            "resume_evidence_malformed",
            "Process resume evidence is malformed",
        )
    try:
        trigger_ts = datetime.fromisoformat(trigger_raw.replace("Z", "+00:00"))
        mode = Mode(mode_raw)
    except ValueError as exc:
        raise WorkflowResumeError(
            "resume_evidence_malformed",
            "Process resume evidence is malformed",
        ) from exc
    if trigger_ts.tzinfo is None or not isinstance(context_raw, Mapping):
        raise WorkflowResumeError(
            "resume_evidence_malformed",
            "Process resume evidence is malformed",
        )
    context = {
        str(key): str(value)
        for key, value in context_raw.items()
        if isinstance(key, str) and isinstance(value, str)
    }
    if len(context) != len(context_raw):
        raise WorkflowResumeError(
            "resume_evidence_malformed",
            "Process resume evidence is malformed",
        )
    if snapshot.workflow_ref != workflow.name or snapshot.workflow_version != str(workflow.version):
        raise WorkflowResumeError(
            "workflow_version_mismatch",
            "Process workflow identity does not match the loaded catalog version",
        )
    return WorkflowResumeEnvelope(
        process_id=snapshot.process_id,
        workflow_ref=snapshot.workflow_ref,
        workflow_version=snapshot.workflow_version,
        target_resource_id=snapshot.target_resource_id,
        correlation_id=snapshot.correlation_id,
        trigger_ts=trigger_ts,
        mode=mode,
        context=context,
    )


__all__ = [
    "WorkflowResumeEnvelope",
    "WorkflowResumeError",
    "build_resume_payload",
    "load_resume_envelope",
]
