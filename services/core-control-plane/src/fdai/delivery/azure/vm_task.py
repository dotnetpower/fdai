"""Azure Managed Run Command adapter for governed Python VM tasks."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Final
from urllib.parse import urlparse

import httpx

from fdai.shared.providers.vm_task import (
    PythonTaskCapability,
    VmTaskReceipt,
    VmTaskRequest,
    VmTaskRunner,
    VmTaskRunnerError,
    VmTaskStatus,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_ARM_VM_ID = re.compile(
    r"^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/"
    r"Microsoft\.Compute/virtualMachines/[^/]+$",
    re.IGNORECASE,
)
_RUN_NAME = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_DEFAULT_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_API_VERSION: Final[str] = "2024-07-01"


@dataclass(frozen=True, slots=True)
class AzureVmTaskRunnerConfig:
    """Managed Run Command REST and guest execution settings."""

    endpoint: str = _DEFAULT_ENDPOINT
    audience: str = _DEFAULT_AUDIENCE
    api_version: str = _DEFAULT_API_VERSION
    run_as_user: str = "fdai-task"
    task_root: str = "/var/lib/fdai/tasks"
    launcher_path: str = "/usr/local/bin/fdai-task-launch"
    request_timeout_seconds: float = 30.0
    max_error_body_bytes: int = 512

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
            raise ValueError("endpoint MUST be an HTTPS origin")
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", self.run_as_user):
            raise ValueError("run_as_user MUST be a bounded Linux account name")
        if not self.task_root.startswith("/") or ".." in PurePosixPath(self.task_root).parts:
            raise ValueError("task_root MUST be an absolute traversal-free path")
        if (
            not self.launcher_path.startswith("/")
            or ".." in PurePosixPath(self.launcher_path).parts
        ):
            raise ValueError("launcher_path MUST be an absolute traversal-free path")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds MUST be positive")
        if self.max_error_body_bytes < 64:
            raise ValueError("max_error_body_bytes MUST be >= 64")


class AzureVmTaskRunner(VmTaskRunner):
    """Stage and execute task files through a Managed Run Command resource."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureVmTaskRunnerConfig | None = None,
    ) -> None:
        self._identity = identity
        self._http = http_client
        self._config = config or AzureVmTaskRunnerConfig()
        self._artifact_by_ref: dict[str, str] = {}

    async def run(self, request: VmTaskRequest) -> VmTaskReceipt:
        missing = request.task.capabilities - request.target.capabilities
        if missing:
            names = ", ".join(sorted(capability.value for capability in missing))
            raise VmTaskRunnerError(f"target lacks required capabilities: {names}")
        resource_id = _validated_vm_resource_id(request.target.provider_ref or "")
        run_name = _run_name(request)
        run_ref = f"{self._config.endpoint.rstrip('/')}{resource_id}/runCommands/{run_name}"
        if request.dry_run:
            return VmTaskReceipt(
                run_ref=run_ref,
                artifact_hash=request.task.artifact_hash,
                status=VmTaskStatus.PLANNED,
                detail="validated Azure Managed Run Command plan; no request sent",
            )
        if request.target.location is None:
            raise VmTaskRunnerError("Azure VM target location is required for Managed Run Command")

        existing = await self._get(run_ref, allow_missing=True)
        if existing is not None:
            receipt = _receipt_from_payload(
                run_ref,
                existing,
                fallback_hash=request.task.artifact_hash,
                already_existed=True,
            )
            self._artifact_by_ref[run_ref] = receipt.artifact_hash
            return receipt

        body = {
            "location": request.target.location,
            "tags": {
                "fdai-artifact-sha256": request.task.artifact_hash,
                "fdai-task-id": request.task.task_id,
            },
            "properties": {
                "source": {
                    "script": _render_script(
                        request,
                        self._config.task_root,
                        self._config.run_as_user,
                        self._config.launcher_path,
                    )
                },
                "timeoutInSeconds": request.task.timeout_seconds + 60,
                "asyncExecution": True,
                "runAsUser": "root",
            },
        }
        response = await self._request(
            "PUT",
            run_ref,
            params={"api-version": self._config.api_version},
            json_body=body,
        )
        payload = _response_json(response)
        self._artifact_by_ref[run_ref] = request.task.artifact_hash
        receipt = _receipt_from_payload(
            run_ref,
            payload,
            fallback_hash=request.task.artifact_hash,
        )
        if receipt.status.terminal:
            return receipt
        return VmTaskReceipt(
            run_ref=run_ref,
            artifact_hash=request.task.artifact_hash,
            status=VmTaskStatus.SUBMITTED,
            detail="Managed Run Command accepted",
        )

    async def status(self, run_ref: str) -> VmTaskReceipt:
        self._validate_run_ref(run_ref)
        payload = await self._get(run_ref, allow_missing=False)
        if payload is None:  # pragma: no cover - allow_missing=False invariant
            raise VmTaskRunnerError("Managed Run Command disappeared")
        return _receipt_from_payload(
            run_ref,
            payload,
            fallback_hash=self._artifact_by_ref.get(run_ref, "unknown"),
        )

    async def cancel(self, run_ref: str) -> VmTaskReceipt:
        self._validate_run_ref(run_ref)
        artifact_hash = self._artifact_by_ref.get(run_ref, "unknown")
        payload = await self._get(run_ref, allow_missing=True)
        if payload is not None:
            artifact_hash = _artifact_hash(payload, artifact_hash)
            await self._request(
                "DELETE",
                run_ref,
                params={"api-version": self._config.api_version},
            )
        return VmTaskReceipt(
            run_ref=run_ref,
            artifact_hash=artifact_hash,
            status=VmTaskStatus.CANCELLED,
            detail="Managed Run Command deleted; in-flight execution terminated if present",
            already_existed=payload is None,
        )

    async def _get(self, run_ref: str, *, allow_missing: bool) -> dict[str, Any] | None:
        self._validate_run_ref(run_ref)
        response = await self._request(
            "GET",
            run_ref,
            params={"api-version": self._config.api_version, "$expand": "instanceView"},
            allow_not_found=allow_missing,
        )
        if response.status_code == 404:
            return None
        return _response_json(response)

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str],
        json_body: dict[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> httpx.Response:
        token = await self._identity.get_token(self._config.audience)
        try:
            response = await self._http.request(
                method,
                url,
                params=params,
                headers={"Authorization": f"Bearer {token.token}"},
                json=json_body,
                timeout=self._config.request_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise VmTaskRunnerError(
                f"Azure Run Command request failed: {type(exc).__name__}"
            ) from exc
        if response.status_code == 404 and allow_not_found:
            return response
        if response.status_code >= 400:
            snippet = response.text.encode("utf-8")[: self._config.max_error_body_bytes]
            detail = snippet.decode("utf-8", errors="replace")
            raise VmTaskRunnerError(
                f"Azure Run Command returned HTTP {response.status_code}: {detail}"
            )
        return response

    def _validate_run_ref(self, run_ref: str) -> None:
        expected = self._config.endpoint.rstrip("/")
        parsed = urlparse(run_ref)
        endpoint = urlparse(expected)
        if parsed.scheme != endpoint.scheme or parsed.netloc != endpoint.netloc:
            raise VmTaskRunnerError("run_ref host does not match the configured ARM endpoint")
        marker = "/runCommands/"
        if marker not in parsed.path:
            raise VmTaskRunnerError("run_ref is not a VM Run Command resource")
        resource_id, run_name = parsed.path.rsplit(marker, 1)
        _validated_vm_resource_id(resource_id)
        if not _RUN_NAME.fullmatch(run_name):
            raise VmTaskRunnerError("run_ref contains an invalid Run Command name")


def _render_script(
    request: VmTaskRequest,
    task_root: str,
    run_as_user: str,
    launcher_path: str,
) -> str:
    """Render a fixed shell harness with only encoded files and validated paths."""

    task = request.task
    artifact = task.artifact_hash
    task_dir = f"{task_root.rstrip('/')}/{artifact}"
    staging = f"{task_dir}.staging"
    run_key = hashlib.sha256(request.idempotency_key.encode()).hexdigest()[:24]
    run_dir = f"{task_root.rstrip('/')}/.runs/{run_key}"
    lines = [
        "set -eu",
        "umask 077",
        f"task_dir={shlex.quote(task_dir)}",
        f"staging={shlex.quote(staging)}",
        'test "$(id -u)" = 0',
        f"test -x {shlex.quote(launcher_path)}",
        'if [ ! -f "$task_dir/.fdai-artifact" ]; then',
        '  rm -rf -- "$staging"',
        '  install -d -m 0700 "$staging"',
    ]
    for item in sorted(task.files, key=lambda value: value.path):
        parent = str(PurePosixPath(item.path).parent)
        if parent != ".":
            lines.append(f'  install -d -m 0700 "$staging/{parent}"')
        encoded = base64.b64encode(item.content.encode("utf-8")).decode("ascii")
        quoted_path = shlex.quote(item.path)
        lines.extend(
            [
                f'  printf %s {shlex.quote(encoded)} | base64 -d > "$staging/"{quoted_path}',
                f"  printf '%s  %s\\n' {shlex.quote(item.sha256)} {quoted_path} "
                '| (cd "$staging" && sha256sum -c -)',
                f'  chmod 0600 "$staging/"{quoted_path}',
            ]
        )
    capability_csv = ",".join(sorted(value.value for value in task.capabilities))
    lines.extend(
        [
            f"  printf '%s\\n' {shlex.quote(artifact)} > \"$staging/.fdai-artifact\"",
            '  rm -rf -- "$task_dir"',
            '  mv -- "$staging" "$task_dir"',
            "fi",
            f'test "$(cat "$task_dir/.fdai-artifact")" = {shlex.quote(artifact)}',
        ]
    )
    for item in sorted(task.files, key=lambda value: value.path):
        quoted_path = shlex.quote(item.path)
        lines.append(
            f"printf '%s  %s\\n' {shlex.quote(item.sha256)} {quoted_path} "
            '| (cd "$task_dir" && sha256sum -c -)'
        )
    if PythonTaskCapability.GPU in task.capabilities:
        lines.extend(["command -v nvidia-smi >/dev/null", "nvidia-smi -L >/dev/null"])
    modules_json = json.dumps(list(task.required_modules), separators=(",", ":"))
    module_probe = (
        "import importlib.util,json,sys; mods=json.loads(sys.argv[1]); "
        "missing=[m for m in mods if importlib.util.find_spec(m) is None]; "
        "print(json.dumps({'missing_modules':missing})); sys.exit(bool(missing))"
    )
    inputs = base64.b64encode(
        json.dumps(dict(request.inputs), sort_keys=True).encode("utf-8")
    ).decode("ascii")
    lines.extend(
        [
            f"{shlex.quote(task.python_executable)} -c {shlex.quote(module_probe)} "
            f"{shlex.quote(modules_json)}",
            f"run_dir={shlex.quote(run_dir)}",
            'rm -rf -- "$run_dir"',
            'install -d -m 0700 "$run_dir"',
            f'printf %s {shlex.quote(inputs)} | base64 -d > "$run_dir/inputs.json"',
            f"{shlex.quote(launcher_path)} "
            f'{shlex.quote(run_as_user)} "$task_dir" "$run_dir" '
            f"{shlex.quote(task.python_executable)} {shlex.quote(task.entrypoint)} "
            f"{task.timeout_seconds} {shlex.quote(capability_csv)}",
        ]
    )
    return "\n".join(lines) + "\n"


def _validated_vm_resource_id(value: str) -> str:
    if not _ARM_VM_ID.fullmatch(value):
        raise VmTaskRunnerError("target resource_ref MUST be an Azure VM ARM resource id")
    return value


def _run_name(request: VmTaskRequest) -> str:
    key_hash = hashlib.sha256(request.idempotency_key.encode("utf-8")).hexdigest()[:12]
    return f"fdai-{request.task.artifact_hash[:24]}-{key_hash}"


def _response_json(response: httpx.Response) -> dict[str, Any]:
    if not response.content:
        return {}
    try:
        payload = response.json()
    except ValueError as exc:
        raise VmTaskRunnerError("Azure Run Command returned non-JSON content") from exc
    if not isinstance(payload, dict):
        raise VmTaskRunnerError("Azure Run Command response MUST be a JSON object")
    return payload


def _receipt_from_payload(
    run_ref: str,
    payload: dict[str, Any],
    *,
    fallback_hash: str,
    already_existed: bool = False,
) -> VmTaskReceipt:
    raw_properties = payload.get("properties")
    properties: dict[str, Any] = raw_properties if isinstance(raw_properties, dict) else {}
    raw_view = properties.get("instanceView")
    view: dict[str, Any] = raw_view if isinstance(raw_view, dict) else {}
    raw_state = str(
        view.get("executionState") or properties.get("provisioningState") or "running"
    ).lower()
    status = {
        "succeeded": VmTaskStatus.SUCCEEDED,
        "success": VmTaskStatus.SUCCEEDED,
        "failed": VmTaskStatus.FAILED,
        "canceled": VmTaskStatus.CANCELLED,
        "cancelled": VmTaskStatus.CANCELLED,
        "running": VmTaskStatus.RUNNING,
    }.get(raw_state, VmTaskStatus.SUBMITTED)
    exit_code = view.get("exitCode")
    return VmTaskReceipt(
        run_ref=run_ref,
        artifact_hash=_artifact_hash(payload, fallback_hash),
        status=status,
        detail=f"Azure Managed Run Command state: {raw_state}",
        already_existed=already_existed,
        exit_code=exit_code if isinstance(exit_code, int) else None,
        stdout_tail=str(view.get("output") or "")[-4_096:],
        stderr_tail=str(view.get("error") or "")[-4_096:],
    )


def _artifact_hash(payload: dict[str, Any], fallback: str) -> str:
    tags = payload.get("tags")
    if isinstance(tags, dict):
        value = tags.get("fdai-artifact-sha256")
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
            return value
    return fallback


__all__ = ["AzureVmTaskRunner", "AzureVmTaskRunnerConfig"]
