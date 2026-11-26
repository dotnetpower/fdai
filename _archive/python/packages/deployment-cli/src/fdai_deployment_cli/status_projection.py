"""Sanitized provisioning status shared by CLI and operator projections."""

from __future__ import annotations

from collections.abc import Sequence

from fdai_deployment_cli.compiler import GENESIS_ENTRY_IDS_BY_VERSION
from fdai_deployment_cli.progress import ProgressSnapshot
from fdai_deployment_cli.state import ProvisionEvent, RunState

_TERMINAL_STAGE_STATES = frozenset({RunState.COMPLETED, RunState.READY})


def project_status(
    events: Sequence[ProvisionEvent],
    *,
    progress: ProgressSnapshot | None = None,
) -> dict[str, object]:
    """Project one bounded run without exposing target or evidence identifiers."""

    if not events:
        raise ValueError("provision journal is empty")
    latest = events[-1]
    if any(event.run_id != latest.run_id for event in events):
        raise ValueError("provision journal contains multiple run ids")
    stage_ids = GENESIS_ENTRY_IDS_BY_VERSION[latest.manifest_version]
    completed = {
        event.stage
        for event in events
        if event.state in _TERMINAL_STAGE_STATES and event.stage in stage_ids
    }
    stages = [
        {
            "id": stage,
            "status": _stage_status(stage, latest=latest, completed=completed),
        }
        for stage in stage_ids
    ]
    currently_completed = {str(stage["id"]) for stage in stages if stage["status"] == "completed"}
    ready = latest.state is RunState.READY
    result: dict[str, object] = {
        "schema_version": "fdai.provision-status.v1",
        "type": "provision.snapshot",
        "run_id": latest.run_id,
        "sequence": latest.sequence,
        "attempt": latest.attempt,
        "state": latest.state.value,
        "current_stage": latest.stage,
        "stages_completed": len(currently_completed),
        "stages_total": len(stage_ids),
        "last_progress_at": latest.occurred_at,
        "reason_code": latest.reason_code,
        "ready": ready,
        "readiness": {
            "database": "database" in currently_completed,
            "semantic": "semantic-defaults" in currently_completed,
            "models": "model-deployments" in currently_completed,
            "runtime": "console" in currently_completed,
            "inventory": "initial-inventory" in currently_completed,
            "system": ready,
        },
        "stages": stages,
    }
    if progress is not None:
        if progress.sequence > latest.sequence:
            raise ValueError("progress sequence cannot exceed the journal sequence")
        result["checkpoints_completed"] = progress.checkpoints_completed
        result["checkpoints_total"] = progress.checkpoints_total
        result["inventory"] = {
            "resources_observed": progress.resources_observed,
            "resources_expected": progress.resources_expected,
            "pages_completed": progress.pages_completed,
            "pages_expected": progress.pages_expected,
        }
    return result


def _stage_status(
    stage: str,
    *,
    latest: ProvisionEvent,
    completed: set[str],
) -> str:
    if stage == latest.stage:
        if latest.state in _TERMINAL_STAGE_STATES:
            return "completed"
        if latest.state is RunState.WAITING:
            return "waiting"
        if latest.state in {RunState.BLOCKED, RunState.FAILED, RunState.INCOMPLETE}:
            return latest.state.value
        if latest.state is RunState.CANCELLED:
            return "cancelled"
        return "active"
    return "completed" if stage in completed else "pending"


__all__ = ["project_status"]
