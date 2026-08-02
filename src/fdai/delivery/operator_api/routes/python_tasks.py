"""Governed Python task authoring, shadow testing, and run-request routes."""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from fdai.core.python_task import validate_python_task
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Capability, has_capability
from fdai.core.scheduler.store import ScheduleStore
from fdai.core.workflow.schedule import scheduled_task_from_workflow
from fdai.shared.contracts.models import Workflow
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.python_task_author import (
    PythonTaskAuthor,
    PythonTaskAuthorRequest,
)
from fdai.shared.providers.vm_task import (
    PythonTaskArtifactStore,
    PythonTaskCapability,
    PythonTaskFile,
    PythonTaskSpec,
    VmTaskRequest,
    VmTaskRunner,
    VmTaskTargetResolver,
    python_task_to_mapping,
)

BASE_PATH: Final[str] = "/python-tasks"
MAX_BODY_BYTES: Final[int] = 600_000
_WRITE_CAPABILITY: Final[Capability] = Capability.AUTHOR_DRAFT_PR

AuthorizeOid = Callable[[Request], Awaitable[str]]
AuthorizePrincipal = Callable[[Request], Awaitable[Principal]]


@dataclass(frozen=True, slots=True)
class PythonTaskRunSubmitter:
    """Publish a VM task ActionProposal into the typed control loop."""

    event_bus: EventBus
    topic: str

    def __post_init__(self) -> None:
        if not self.topic:
            raise ValueError("Python task proposal topic MUST be non-empty")

    async def submit(
        self,
        *,
        principal: Principal,
        artifact_ref: str,
        target_resource_ref: str,
        reason: str,
        idempotency_key: str | None,
    ) -> dict[str, object]:
        correlation_id = f"vm-task-{uuid.uuid4()}"
        client_key = (idempotency_key or correlation_id).strip()
        if not client_key or len(client_key) > 200:
            raise ValueError("idempotency_key MUST be a bounded non-empty string")
        dedupe = f"{principal.oid}::{client_key}"[:200]
        proposal = {
            "idempotency_key": dedupe,
            "correlation_id": correlation_id,
            "initiator_principal": principal.oid,
            "operator_initiated": True,
            "action_type": "tool.run-python-on-vm",
            "resource_id": target_resource_ref,
            "event_type": "operator_request",
            "params": {
                "artifact_ref": artifact_ref,
                "target_resource_ref": target_resource_ref,
                "reason": reason,
            },
        }
        await self.event_bus.publish(self.topic, target_resource_ref, proposal)
        return {
            "submitted": True,
            "correlation_id": correlation_id,
            "action_type": "tool.run-python-on-vm",
            "artifact_ref": artifact_ref,
            "target_resource_ref": target_resource_ref,
        }


@dataclass(frozen=True, slots=True)
class PythonTaskRoutesConfig:
    artifacts: PythonTaskArtifactStore
    targets: VmTaskTargetResolver
    runner: VmTaskRunner
    submitter: PythonTaskRunSubmitter | None = None
    schedule_store: ScheduleStore | None = None
    workflows: tuple[Workflow, ...] = ()
    author: PythonTaskAuthor | None = None
    prefix: str = BASE_PATH


def build_python_task_routes(
    *,
    config: PythonTaskRoutesConfig,
    authorize_oid: AuthorizeOid,
    authorize_principal: AuthorizePrincipal,
) -> list[Route]:
    """Build task validation, immutable staging, dry-run, and proposal routes."""

    prefix = config.prefix.rstrip("/") or BASE_PATH
    if not prefix.startswith("/"):
        raise ValueError("Python task route prefix MUST start with '/'")

    async def capabilities(request: Request) -> JSONResponse:
        await authorize_oid(request)
        return JSONResponse(
            {
                "available": True,
                "operations": {
                    "generate": config.author is not None,
                    "validate": True,
                    "stage": True,
                    "test": True,
                    "request_run": config.submitter is not None,
                    "schedule": config.schedule_store is not None,
                },
            }
        )

    async def validate_task(request: Request) -> JSONResponse:
        await authorize_oid(request)
        raw = await _json_body(request)
        task = _task_from_mapping(_mapping(raw, "request body"))
        return JSONResponse(_validation_payload(task))

    async def generate_task(request: Request) -> JSONResponse:
        principal = await authorize_principal(request)
        _require_write(principal)
        if config.author is None:
            raise HTTPException(status_code=501, detail="Python task author is not wired")
        raw = _mapping(await _json_body(request), "request body")
        intent = _bounded_string(raw, "intent", 4_000)
        task_id_hint = _bounded_string(raw, "task_id_hint", 80)
        target_ref = _bounded_string(raw, "target_resource_ref", 2_048)
        allowed_modules = _string_list(raw.get("allowed_modules"), "allowed_modules")
        if len(allowed_modules) > 64:
            raise HTTPException(
                status_code=400,
                detail="allowed_modules MUST contain at most 64 entries",
            )
        target = await config.targets.resolve(target_ref)
        try:
            task = await config.author.author(
                PythonTaskAuthorRequest(
                    intent=intent,
                    task_id_hint=task_id_hint,
                    target_capabilities=target.capabilities,
                    allowed_modules=tuple(allowed_modules),
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(
            {
                "task": python_task_to_mapping(task),
                "validation": _validation_payload(task),
            },
            status_code=200,
        )

    async def stage_task(request: Request) -> JSONResponse:
        principal = await authorize_principal(request)
        _require_write(principal)
        raw = await _json_body(request)
        task = _task_from_mapping(_mapping(raw, "request body"))
        report = validate_python_task(task)
        if not report.valid:
            return JSONResponse(_validation_payload(task), status_code=422)
        artifact_ref = await config.artifacts.put(task, created_by=principal.oid)
        return JSONResponse(
            {
                **_validation_payload(task),
                "staged": True,
                "artifact_ref": artifact_ref,
            }
        )

    async def test_task(request: Request) -> JSONResponse:
        principal = await authorize_principal(request)
        _require_write(principal)
        raw = _mapping(await _json_body(request), "request body")
        task = _task_from_mapping(_mapping(raw.get("task"), "task"))
        report = validate_python_task(task)
        if not report.valid:
            return JSONResponse(_validation_payload(task), status_code=422)
        target_ref = _bounded_string(raw, "target_resource_ref", 2_048)
        target = await config.targets.resolve(target_ref)
        receipt = await config.runner.run(
            VmTaskRequest(
                idempotency_key=f"test:{principal.oid}:{task.artifact_hash}",
                task=task,
                target=target,
                dry_run=True,
            )
        )
        return JSONResponse(
            {
                **_validation_payload(task),
                "plan": {
                    "run_ref": receipt.run_ref,
                    "status": receipt.status.value,
                    "detail": receipt.detail,
                    "target_resource_ref": target.resource_ref,
                    "target_capabilities": sorted(value.value for value in target.capabilities),
                    "files_would_copy": len(task.files),
                    "bytes_would_copy": sum(
                        len(item.content.encode("utf-8")) for item in task.files
                    ),
                },
            }
        )

    async def request_run(request: Request) -> JSONResponse:
        principal = await authorize_principal(request)
        _require_write(principal)
        if config.submitter is None:
            raise HTTPException(status_code=501, detail="Python task run submission is not wired")
        raw = _mapping(await _json_body(request), "request body")
        artifact_ref = _bounded_string(raw, "artifact_ref", 256)
        target_ref = _bounded_string(raw, "target_resource_ref", 2_048)
        reason = _bounded_string(raw, "reason", 200)
        if len(reason) < 10:
            raise HTTPException(status_code=400, detail="reason MUST be at least 10 characters")
        await config.artifacts.get(artifact_ref)
        await config.targets.resolve(target_ref)
        idempotency = raw.get("idempotency_key")
        if idempotency is not None and not isinstance(idempotency, str):
            raise HTTPException(status_code=400, detail="idempotency_key MUST be a string")
        try:
            result = await config.submitter.submit(
                principal=principal,
                artifact_ref=artifact_ref,
                target_resource_ref=target_ref,
                reason=reason,
                idempotency_key=idempotency,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(result, status_code=202)

    async def create_schedule(request: Request) -> JSONResponse:
        principal = await authorize_principal(request)
        _require_write(principal)
        if config.schedule_store is None:
            raise HTTPException(status_code=501, detail="Python task scheduling is not wired")
        raw = _mapping(await _json_body(request), "request body")
        artifact_ref = _bounded_string(raw, "artifact_ref", 256)
        target_ref = _bounded_string(raw, "target_resource_ref", 2_048)
        workflow_ref = _bounded_string(raw, "workflow_ref", 80)
        cron_expression = _bounded_string(raw, "cron_expression", 100)
        await config.artifacts.get(artifact_ref)
        await config.targets.resolve(target_ref)
        workflow = next(
            (item for item in config.workflows if item.name == workflow_ref),
            None,
        )
        if workflow is None:
            raise HTTPException(status_code=404, detail=f"unknown workflow {workflow_ref!r}")
        try:
            task = scheduled_task_from_workflow(
                workflow,
                target_resource_ref=target_ref,
                artifact_ref=artifact_ref,
                created_by=principal.oid,
                cron_expression=cron_expression,
            )
            created = await config.schedule_store.create(task)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(
            {
                "scheduled": True,
                "task_id": created.task_id,
                "workflow_ref": workflow.name,
                "artifact_ref": artifact_ref,
                "target_resource_ref": target_ref,
                "cron_expression": created.cron_expression,
                "event_type": created.event_type,
            },
            status_code=201,
        )

    return [
        Route(f"{prefix}/capabilities", capabilities, methods=["GET"]),
        Route(f"{prefix}/generate", generate_task, methods=["POST"]),
        Route(f"{prefix}/validate", validate_task, methods=["POST"]),
        Route(f"{prefix}/stage", stage_task, methods=["POST"]),
        Route(f"{prefix}/test", test_task, methods=["POST"]),
        Route(f"{prefix}/request-run", request_run, methods=["POST"]),
        Route(f"{prefix}/schedule", create_schedule, methods=["POST"]),
    ]


async def _json_body(request: Request) -> object:
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Python task request body is too large")
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="request body MUST be valid JSON") from exc


def _task_from_mapping(raw: Mapping[str, object]) -> PythonTaskSpec:
    try:
        files_raw = raw.get("files")
        if not isinstance(files_raw, list):
            raise ValueError("files MUST be an array")
        files = tuple(
            PythonTaskFile(
                path=_bounded_string(_mapping(item, "file"), "path", 200),
                content=_bounded_string(_mapping(item, "file"), "content", 128 * 1024),
            )
            for item in files_raw
        )
        modules = _string_list(raw.get("required_modules"), "required_modules")
        capability_names = _string_list(raw.get("capabilities"), "capabilities")
        capabilities = frozenset(PythonTaskCapability(value) for value in capability_names)
        timeout = raw.get("timeout_seconds", 900)
        if not isinstance(timeout, int) or isinstance(timeout, bool):
            raise ValueError("timeout_seconds MUST be an integer")
        python_executable = raw.get("python_executable", "/usr/bin/python3")
        if not isinstance(python_executable, str):
            raise ValueError("python_executable MUST be a string")
        return PythonTaskSpec(
            task_id=_bounded_string(raw, "task_id", 80),
            version=_bounded_string(raw, "version", 64),
            entrypoint=_bounded_string(raw, "entrypoint", 200),
            files=files,
            required_modules=tuple(modules),
            capabilities=capabilities,
            timeout_seconds=timeout,
            python_executable=python_executable,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validation_payload(task: PythonTaskSpec) -> dict[str, object]:
    report = validate_python_task(task)
    return {
        "valid": report.valid,
        "artifact_hash": report.artifact_hash,
        "artifact_ref": task.artifact_ref if report.valid else None,
        "detected_capabilities": sorted(value.value for value in report.detected_capabilities),
        "imported_modules": list(report.imported_modules),
        "issues": [
            {"code": issue.code, "path": issue.path, "message": issue.message}
            for issue in report.issues
        ],
    }


def _require_write(principal: Principal) -> None:
    if not has_capability(principal.roles, _WRITE_CAPABILITY):
        raise HTTPException(
            status_code=403,
            detail=f"Python task authoring requires capability {_WRITE_CAPABILITY.value!r}",
        )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise HTTPException(status_code=400, detail=f"{label} MUST be an object")
    return value


def _bounded_string(raw: Mapping[str, object], key: str, max_chars: int) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise HTTPException(status_code=400, detail=f"{key} MUST be a non-empty string")
    if len(value) > max_chars:
        raise HTTPException(status_code=400, detail=f"{key} exceeds {max_chars} characters")
    return value


def _string_list(value: object, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} MUST be an array of strings")
    return value


__all__ = [
    "BASE_PATH",
    "PythonTaskRoutesConfig",
    "PythonTaskRunSubmitter",
    "build_python_task_routes",
]
