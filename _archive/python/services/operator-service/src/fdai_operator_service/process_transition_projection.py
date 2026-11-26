"""Project and precheck principal-scoped Process transition requests.

The Operator Service renders only durable Process, event, and reviewed Workflow catalog state.
It may reject an impossible request, but final transition authority remains with the workflow
runtime, which reloads and rechecks the same Process before changing state.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from fdai_service_contracts import OperatorRole

from fdai_operator_service.process_approval_projection import (
    ProcessApprovalProjectionError,
    project_approval_requirements,
)
from fdai_operator_service.process_retry_admission import retry_is_permitted


class ProcessControlUnavailableError(RuntimeError):
    """Required authoritative Process or catalog evidence is unavailable."""


class ProcessTransitionDeniedError(RuntimeError):
    """The requested transition is not currently permitted."""

    def __init__(self, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ProcessControlState:
    """One revision-bound principal-scoped Process control projection."""

    payload: dict[str, object]
    permitted_transition_ids: frozenset[str]


def project_process_control(
    *,
    process: Mapping[str, object],
    events: Sequence[Mapping[str, object]],
    workflow_catalog: Mapping[str, object],
    principal_id: str,
    roles: frozenset[OperatorRole],
    approval_state: Mapping[str, object] | None = None,
) -> ProcessControlState:
    """Build current step requirements and requests allowed by durable evidence."""
    process_id = _required_text(process, "process_id")
    workflow_ref = _required_text(process, "workflow_ref")
    workflow_version = _required_text(process, "workflow_version")
    status = _required_text(process, "status")
    current_step = _required_text(process, "current_step", allow_empty=True)
    revision = _required_integer(process, "revision")
    created = _created_event(events)
    resume = _mapping(_mapping(created.get("payload"), "creation payload").get("resume"), "resume")
    context = _mapping(resume.get("context"), "resume context")
    requester = _required_text(context, "requester.principal")
    if _normalize_principal(requester) != _normalize_principal(principal_id):
        raise ProcessTransitionDeniedError("Process is not visible to the authenticated principal")
    mode = _required_text(resume, "mode")
    if mode not in {"shadow", "enforce"}:
        raise ProcessControlUnavailableError("Process mode evidence is malformed")

    workflow, catalog_revision = _workflow(
        workflow_catalog,
        workflow_ref=workflow_ref,
        workflow_version=workflow_version,
    )
    steps = workflow.get("steps")
    if not isinstance(steps, list):
        raise ProcessControlUnavailableError("Workflow catalog steps are malformed")
    step = next(
        (
            _mapping(item, "workflow step")
            for item in steps
            if isinstance(item, Mapping) and item.get("id") == current_step
        ),
        None,
    )
    if current_step and step is None:
        raise ProcessControlUnavailableError(
            "Current Process step is absent from the pinned Workflow"
        )

    attempt = max((_event_attempt(event) for event in events), default=1)
    latest = next(
        (
            event
            for event in reversed(events)
            if event.get("step_id") == current_step and isinstance(event.get("payload"), Mapping)
        ),
        None,
    )
    latest_payload = _mapping(latest.get("payload"), "latest step payload") if latest else {}
    step_kind = (
        _required_text(step, "kind")
        if step is not None and isinstance(step.get("kind"), str)
        else str(latest_payload.get("step_kind") or "action")
    )
    requirements = _requirements(
        step_kind,
        step,
        latest_payload,
        events,
        current_step,
        attempt,
        process_id,
        requester,
        approval_state,
    )
    transitions = _transitions(
        process_id=process_id,
        status=status,
        step_kind=step_kind,
        mode=mode,
        roles=roles,
        revision=revision,
        events=events,
        attempt=attempt,
    )
    reason = latest_payload.get("reason")
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "authoritative": True,
        "principal_scoped": True,
        "available": True,
        "process_revision": revision,
        "catalog_revision": catalog_revision,
        "mode": mode,
        "step": {
            "id": current_step,
            "kind": step_kind,
            "state": status,
            "attempt": attempt,
            "reason": str(reason) if isinstance(reason, str) and reason else None,
            "requirements": requirements,
        },
        "permitted_transitions": transitions,
        "acceptance_is_success": False,
    }
    return ProcessControlState(
        payload=payload,
        permitted_transition_ids=frozenset(
            str(transition["id"]) for transition in transitions if transition["method"] == "POST"
        ),
    )


def authorize_process_transition(
    *,
    operation: str,
    expected_revision: str,
    state: ProcessControlState,
) -> None:
    """Reject a stale or currently impermissible proposal before persistence."""
    try:
        expected = int(expected_revision)
    except ValueError as exc:
        raise ProcessTransitionDeniedError("If-Match MUST be the numeric Process revision") from exc
    revision = state.payload["process_revision"]
    if expected != revision:
        raise ProcessTransitionDeniedError("Process revision is stale; refresh before retrying")
    transition_id = {
        "workflow.resume-request": "resume",
        "workflow.cancel-request": "cancel",
        "workflow.retry-request": "retry",
    }.get(operation)
    if transition_id is None or transition_id not in state.permitted_transition_ids:
        raise ProcessTransitionDeniedError(
            "Transition is not permitted by the current Process state"
        )


def _requirements(
    step_kind: str,
    step: Mapping[str, object] | None,
    latest_payload: Mapping[str, object],
    events: Sequence[Mapping[str, object]],
    current_step: str,
    attempt: int,
    process_id: str,
    requester: str,
    approval_state: Mapping[str, object] | None,
) -> dict[str, object]:
    if step is None:
        return {}
    requirements: dict[str, object] = {}
    if step_kind == "wait":
        requirements["wait_for"] = _required_text(step, "wait_for")
        requirements["timeout_seconds"] = _required_integer(step, "timeout_seconds")
        requirements["deadline_at"] = _deadline(
            events,
            current_step,
            attempt,
            requirements["timeout_seconds"],
        )
    elif step_kind == "approval":
        try:
            approval = project_approval_requirements(
                approval_state,
                process_id=process_id,
                step_id=current_step,
                attempt=attempt,
                requester=requester,
            )
        except ProcessApprovalProjectionError as exc:
            raise ProcessControlUnavailableError(str(exc)) from exc
        requirements["approval_role"] = _required_text(step, "approval_role")
        requirements["quorum"] = _required_integer(step, "quorum", default=1)
        requirements["no_self_approval"] = _required_boolean(
            step,
            "no_self_approval",
            default=True,
        )
        requirements["timeout_seconds"] = _required_integer(step, "timeout_seconds")
        if (
            approval["approval_role"] != requirements["approval_role"]
            or approval["quorum"] != requirements["quorum"]
            or approval["no_self_approval"] != requirements["no_self_approval"]
            or approval["timeout_seconds"] != requirements["timeout_seconds"]
        ):
            raise ProcessControlUnavailableError(
                "Durable approval requirements do not match the pinned Workflow"
            )
        requirements.update(approval)
    elif step_kind == "decision":
        requirements["outcomes"] = _string_list(step.get("outcomes"), "decision outcomes")
        requirements["decision"] = str(latest_payload.get("decision") or "pending")
    elif step_kind == "parallel":
        branches = _string_list(step.get("branches"), "parallel branches")
        requirements["branches"] = branches
        requirements["join"] = "all"
        requirements["completed_branches"] = sorted(
            _branch_names(events, current_step, attempt, "parallel.branch.completed")
        )
        requirements["failed_branches"] = sorted(
            _branch_names(events, current_step, attempt, "parallel.branch.failed")
        )
    elif step_kind == "gate":
        requirements["gate_ref"] = _required_text(step, "gate_ref")
        requirements["evidence_state"] = (
            "passed"
            if latest_payload.get("reason") == "gate_passed"
            else "failed"
            if latest_payload.get("reason") == "gate_blocked"
            else "pending"
        )
    return requirements


def _transitions(
    *,
    process_id: str,
    status: str,
    step_kind: str,
    mode: str,
    roles: frozenset[OperatorRole],
    revision: int,
    events: Sequence[Mapping[str, object]],
    attempt: int,
) -> list[dict[str, object]]:
    contributor = bool(
        roles & frozenset({OperatorRole.CONTRIBUTOR, OperatorRole.APPROVER, OperatorRole.OWNER})
    )
    owner_required = mode == "enforce"
    can_request = OperatorRole.OWNER in roles if owner_required else contributor
    transitions: list[dict[str, object]] = []
    if can_request and status == "waiting" and step_kind != "approval":
        transitions.append(_post_transition(process_id, "resume", revision))
    if can_request and status in {"pending", "waiting"}:
        transitions.append(_post_transition(process_id, "cancel", revision))
    if can_request and retry_is_permitted(status=status, events=events, attempt=attempt):
        transitions.append(_post_transition(process_id, "retry", revision))
    return transitions


def _post_transition(process_id: str, transition_id: str, revision: int) -> dict[str, object]:
    return {
        "id": transition_id,
        "method": "POST",
        "path": f"/workflows/{process_id}/{transition_id}",
        "expected_revision": revision,
        "requires_confirmation": transition_id in {"cancel", "retry"},
        "runtime_recheck": True,
    }


def _workflow(
    catalog: Mapping[str, object],
    *,
    workflow_ref: str,
    workflow_version: str,
) -> tuple[Mapping[str, object], str]:
    revision = _required_text(catalog, "_revision")
    workflows = catalog.get("workflows")
    if not isinstance(workflows, list):
        raise ProcessControlUnavailableError("Workflow catalog projection is malformed")
    for raw in workflows:
        if not isinstance(raw, Mapping):
            raise ProcessControlUnavailableError("Workflow catalog entry is malformed")
        if raw.get("name") == workflow_ref and raw.get("version") == workflow_version:
            return raw, revision
    raise ProcessControlUnavailableError("Pinned Process workflow is unavailable from the catalog")


def _created_event(events: Sequence[Mapping[str, object]]) -> Mapping[str, object]:
    created = next((event for event in events if event.get("kind") == "process.created"), None)
    if created is None:
        raise ProcessControlUnavailableError("Process creation evidence is unavailable")
    return created


def _deadline(
    events: Sequence[Mapping[str, object]],
    step_id: str,
    attempt: int,
    timeout_seconds: object,
) -> str:
    started = next(
        (
            event.get("recorded_at")
            for event in reversed(events)
            if event.get("kind") == "step.started"
            and event.get("step_id") == step_id
            and _event_attempt(event) == attempt
        ),
        None,
    )
    if not isinstance(started, datetime):
        raise ProcessControlUnavailableError("Current step start time is unavailable")
    timeout = cast(int, timeout_seconds)
    return (started.astimezone(UTC) + timedelta(seconds=timeout)).isoformat()


def _branch_names(
    events: Sequence[Mapping[str, object]],
    step_id: str,
    attempt: int,
    kind: str,
) -> set[str]:
    names: set[str] = set()
    for event in events:
        if (
            event.get("kind") == kind
            and event.get("step_id") == step_id
            and _event_attempt(event) == attempt
        ):
            branch = _mapping(event.get("payload"), "parallel branch payload").get("branch")
            if not isinstance(branch, str) or not branch:
                raise ProcessControlUnavailableError("Parallel branch evidence is malformed")
            names.add(branch)
    return names


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProcessControlUnavailableError(f"{label} is unavailable or malformed")
    return cast(Mapping[str, object], value)


def _required_text(
    value: Mapping[str, object],
    key: str,
    *,
    allow_empty: bool = False,
) -> str:
    result = value.get(key)
    if not isinstance(result, str) or (not allow_empty and not result.strip()):
        raise ProcessControlUnavailableError(f"{key} is unavailable or malformed")
    return result


def _required_integer(
    value: Mapping[str, object],
    key: str,
    *,
    default: int | None = None,
) -> int:
    result = value.get(key, default)
    if not isinstance(result, int) or isinstance(result, bool) or result < 1:
        raise ProcessControlUnavailableError(f"{key} is unavailable or malformed")
    return result


def _required_boolean(
    value: Mapping[str, object],
    key: str,
    *,
    default: bool,
) -> bool:
    result = value.get(key, default)
    if not isinstance(result, bool):
        raise ProcessControlUnavailableError(f"{key} is unavailable or malformed")
    return result


def _string_list(value: object, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) < 2
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise ProcessControlUnavailableError(f"{label} are unavailable or malformed")
    return value


def _event_attempt(event: Mapping[str, object]) -> int:
    attempt = event.get("attempt", 1)
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise ProcessControlUnavailableError("Process event attempt is malformed")
    return attempt


def _normalize_principal(value: str) -> str:
    return value.strip().casefold()


__all__ = [
    "ProcessControlState",
    "ProcessControlUnavailableError",
    "ProcessTransitionDeniedError",
    "authorize_process_transition",
    "project_process_control",
]
