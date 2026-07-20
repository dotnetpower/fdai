"""Contributor-gated command route for starting a catalog Workflow in shadow.

This is a command surface for CLI and ChatOps adapters, not a console control.
The injected :class:`WorkflowOrchestrator` is shadow-only by construction, so
accepting a run can write Process and audit records but cannot mutate a cloud
resource. The operator console remains a Reader-gated projection over those
records.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Route

from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Capability, Role, has_capability
from fdai.core.workflow.orchestrator import WorkflowOrchestrator
from fdai.shared.contracts.models import Mode, Workflow

DEFAULT_RUN_PATH: Final[str] = "/workflows/run"
DEFAULT_MAX_BODY_BYTES: Final[int] = 32_000
MAX_CONTEXT_ENTRIES: Final[int] = 100
MAX_CONTEXT_VALUE_CHARS: Final[int] = 2_000
MAX_IDENTIFIER_CHARS: Final[int] = 200
_RUN_CAPABILITY: Final[Capability] = Capability.AUTHOR_DRAFT_PR

AuthorizePrincipal = Callable[[Request], Awaitable[Principal]]


@dataclass(frozen=True, slots=True)
class WorkflowExecutionConfig:
    """Catalog and governed orchestrator exposed through the command route."""

    workflows: tuple[Workflow, ...]
    orchestrator: WorkflowOrchestrator
    path: str = DEFAULT_RUN_PATH
    enforce_workflows: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.path.startswith("/"):
            raise ValueError("workflow execution path MUST start with '/'")
        names = [workflow.name for workflow in self.workflows]
        if len(names) != len(set(names)):
            raise ValueError("workflow execution catalog names MUST be unique")
        unknown = self.enforce_workflows - set(names)
        if unknown:
            raise ValueError(f"unknown enforce workflows: {', '.join(sorted(unknown))}")


def make_workflow_run_route(
    *,
    config: WorkflowExecutionConfig,
    authorize_principal: AuthorizePrincipal,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
) -> Route:
    """Return ``POST /workflows/run`` for Contributor-gated shadow runs."""

    workflows = {workflow.name: workflow for workflow in config.workflows}

    async def handler(request: Request) -> JSONResponse:
        principal = await authorize_principal(request)
        if not has_capability(principal.roles, _RUN_CAPABILITY):
            raise HTTPException(
                status_code=403,
                detail=f"workflow run requires capability {_RUN_CAPABILITY.value!r}",
            )
        body = await request.body()
        if len(body) > max_body_bytes:
            raise HTTPException(status_code=413, detail="workflow run request body is too large")
        try:
            raw = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail="request body MUST be valid JSON") from exc
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="request body MUST be a JSON object")

        workflow_name = _required_string(raw, "workflow", max_chars=MAX_IDENTIFIER_CHARS)
        workflow = workflows.get(workflow_name)
        if workflow is None:
            raise HTTPException(status_code=404, detail=f"unknown workflow {workflow_name!r}")
        mode = _mode(raw.get("mode"))
        if mode is Mode.ENFORCE:
            if Role.OWNER not in principal.roles:
                raise HTTPException(status_code=403, detail="enforce workflow run requires Owner")
            if workflow_name not in config.enforce_workflows:
                raise HTTPException(
                    status_code=409,
                    detail=f"workflow {workflow_name!r} is not enabled for enforce runs",
                )
        target = _required_string(raw, "target_resource_id", max_chars=MAX_IDENTIFIER_CHARS)
        trigger_ts = _timestamp(raw.get("trigger_ts"))
        correlation_id = _optional_string(
            raw,
            "correlation_id",
            max_chars=MAX_IDENTIFIER_CHARS,
        )
        context = _context(raw.get("context"))
        context.setdefault("requester.principal", principal.oid)

        run = await config.orchestrator.run(
            workflow,
            target_resource_id=target,
            trigger_ts=trigger_ts,
            context=context,
            correlation_id=correlation_id,
            mode=mode,
        )
        process_path = f"/views/process/{run.process_id}"
        return JSONResponse(
            {
                "process": {
                    "id": run.process_id,
                    "workflow_ref": run.workflow_name,
                    "status": run.status.value,
                    "mode": run.mode,
                    "replayed": run.replayed,
                    "target_resource_id": target,
                    "trigger_ts": trigger_ts.isoformat(),
                },
                "step_results": [
                    {
                        "step_id": result.step_id,
                        "action_type": result.action_type,
                        "outcome": result.outcome.value,
                        "reason": result.reason,
                    }
                    for result in run.step_results
                ],
                "links": {
                    "process": process_path,
                    "events": f"{process_path}/events",
                    "console": f"/processes/{run.process_id}",
                },
            }
        )

    return Route(config.path, handler, methods=["POST"])


def append_workflow_run_route(
    routes: list[BaseRoute],
    *,
    config: WorkflowExecutionConfig | None,
    authorize_principal: AuthorizePrincipal,
    core_paths: frozenset[str],
    panel_paths: set[str],
) -> None:
    """Append the optional route after fail-fast path collision checks."""
    if config is None:
        return
    if config.path in core_paths:
        raise ValueError(f"workflow execution path {config.path!r} collides with a core route")
    if config.path in panel_paths:
        raise ValueError(f"workflow execution path {config.path!r} collides with a panel path")
    routes.append(make_workflow_run_route(config=config, authorize_principal=authorize_principal))


def _required_string(
    raw: Mapping[str, object],
    key: str,
    *,
    max_chars: int,
) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=400, detail=f"{key} MUST be a non-empty string")
    normalized = value.strip()
    if len(normalized) > max_chars:
        raise HTTPException(status_code=400, detail=f"{key} exceeds {max_chars} characters")
    return normalized


def _optional_string(
    raw: Mapping[str, object],
    key: str,
    *,
    max_chars: int,
) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=400, detail=f"{key} MUST be a non-empty string")
    normalized = value.strip()
    if len(normalized) > max_chars:
        raise HTTPException(status_code=400, detail=f"{key} exceeds {max_chars} characters")
    return normalized


def _timestamp(value: object) -> datetime:
    if value is None:
        return datetime.now(tz=UTC)
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail="trigger_ts MUST be an RFC 3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="trigger_ts MUST be an RFC 3339 string",
        ) from exc
    if parsed.tzinfo is None:
        raise HTTPException(status_code=400, detail="trigger_ts MUST include a timezone")
    return parsed.astimezone(UTC)


def _mode(value: object) -> Mode:
    if value is None:
        return Mode.SHADOW
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail="mode MUST be shadow or enforce")
    try:
        return Mode(value.strip().lower())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="mode MUST be shadow or enforce") from exc


def _context(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="context MUST be an object of string values")
    if len(value) > MAX_CONTEXT_ENTRIES:
        raise HTTPException(
            status_code=400,
            detail=f"context exceeds {MAX_CONTEXT_ENTRIES} entries",
        )
    normalized: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key or not isinstance(item, str):
            raise HTTPException(
                status_code=400,
                detail="context MUST be an object of string values",
            )
        if len(key) > MAX_IDENTIFIER_CHARS or len(item) > MAX_CONTEXT_VALUE_CHARS:
            raise HTTPException(status_code=400, detail="context key or value is too long")
        normalized[key] = item
    return normalized


__all__ = [
    "DEFAULT_RUN_PATH",
    "WorkflowExecutionConfig",
    "append_workflow_run_route",
    "make_workflow_run_route",
]
