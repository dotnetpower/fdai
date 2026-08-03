"""SREGym conductor lifecycle adapter."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Final
from urllib.parse import urlsplit

import httpx
from fdai_evaluation_sdk import (
    ArtifactPolicy,
    AuthorityCeiling,
    Capability,
    EvaluationRequest,
    EvaluationResult,
    EvaluationTask,
    MetadataEntry,
    ResourceLimits,
    SideEffectClass,
    TargetRef,
    WorkspacePolicy,
)

_TERMINAL_STAGES: Final[frozenset[str]] = frozenset({"done", "tearing_down"})
_TASK_STAGES: Final[frozenset[str]] = frozenset({"diagnosis", "mitigation", "resolution"})
_PLAINTEXT_HOSTS: Final[frozenset[str]] = frozenset(
    {"127.0.0.1", "localhost", "host.docker.internal"}
)
_DEFAULT_MAX_RESPONSE_BYTES: Final[int] = 1_000_000
_CAPABILITIES: Final[tuple[Capability, ...]] = tuple(
    Capability(capability_id=capability_id, side_effect_class=SideEffectClass.OBSERVE)
    for capability_id in (
        "observe.kubernetes.inventory",
        "observe.kubernetes.events",
        "observe.kubernetes.nodes",
        "observe.metrics.query",
        "observe.logs.query",
        "observe.traces.query",
    )
)


class SregymAdapterError(RuntimeError):
    """Normalized SREGym transport or lifecycle failure."""


@dataclass(frozen=True, slots=True)
class SregymAdapterConfig:
    """Server-owned connection and identity settings for one SREGym run."""

    conductor_url: str
    artifact_id: str
    poll_interval_seconds: float = 1.0
    stage_timeout_seconds: float = 300.0
    request_timeout_seconds: float = 30.0
    max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        parsed = urlsplit(self.conductor_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("conductor_url MUST be an absolute HTTP or HTTPS URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("conductor_url MUST NOT contain credentials, query, or fragment")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("conductor_url port MUST be between 1 and 65535") from exc
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("conductor_url port MUST be between 1 and 65535")
        if parsed.scheme == "http" and parsed.hostname not in _PLAINTEXT_HOSTS:
            raise ValueError(
                "plaintext conductor_url is supported only for loopback or the harness host alias"
            )
        try:
            TargetRef(kind="session", value=self.artifact_id)
        except ValueError as exc:
            raise ValueError("artifact_id MUST be a non-empty bounded identifier") from exc
        timeouts = (
            self.poll_interval_seconds,
            self.stage_timeout_seconds,
            self.request_timeout_seconds,
        )
        if any(not math.isfinite(timeout) or timeout <= 0 for timeout in timeouts):
            raise ValueError("SREGym adapter timeouts MUST be finite and positive")
        if self.max_response_bytes < 1:
            raise ValueError("max_response_bytes MUST be >= 1")


class SregymAdapter:
    """Translate SREGym stages into generic benchmark tasks."""

    adapter_id = "sregym"

    def __init__(
        self,
        *,
        config: SregymAdapterConfig,
        http_client: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._http = http_client or httpx.AsyncClient()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._owns_http = http_client is None
        self._submitted_stage: str | None = None
        self._issued_identity: tuple[str, str, str] | None = None
        self._started = False

    async def start(self) -> EvaluationRequest:
        await self._read_stage()
        self._started = True
        now = self._clock()
        return EvaluationRequest(
            session_id=self._config.artifact_id,
            requester_id="sregym-driver",
            purpose="Evaluate one bounded SREGym operational recovery attempt.",
            requested_capabilities=_CAPABILITIES,
            authority_ceiling=AuthorityCeiling.ENFORCE,
            task_count_limit=3,
            concurrency_limit=1,
            deadline=now + timedelta(seconds=self._config.stage_timeout_seconds * 4),
            workspace_policy=WorkspacePolicy(),
            artifact_policy=ArtifactPolicy(
                allowed_media_types=("application/json",),
                max_artifact_bytes=self._config.max_response_bytes,
            ),
        )

    async def next_task(self) -> EvaluationTask | None:
        if not self._started:
            raise SregymAdapterError("SREGym adapter MUST be started before reading tasks")
        if self._issued_identity is not None:
            raise SregymAdapterError("a SREGym task is already awaiting submission")
        stage = await self._wait_for_next_stage()
        if stage in _TERMINAL_STAGES:
            return None
        app = await self._get_json("/get_app")
        try:
            namespace = _required_text(app, "namespace", max_length=256)
            app_name = _required_text(app, "app_name", max_length=256)
            descriptions = _required_text(app, "descriptions", max_length=20_000)
            task = EvaluationTask(
                session_id=self._config.artifact_id,
                task_id=f"{stage}-{sha256(self._config.artifact_id.encode()).hexdigest()[:16]}",
                phase=stage,
                objective=_objective(stage, app_name=app_name, descriptions=descriptions),
                target=TargetRef(kind="kubernetes.namespace", value=namespace),
                requested_capabilities=_CAPABILITIES,
                deadline=self._clock() + timedelta(seconds=self._config.stage_timeout_seconds),
                resource_limits=ResourceLimits(
                    cpu_seconds=300,
                    memory_bytes=1_073_741_824,
                    process_count=64,
                    output_bytes=self._config.max_response_bytes,
                    wall_clock_seconds=max(1, int(self._config.stage_timeout_seconds)),
                ),
                metadata=(
                    MetadataEntry(key="application", value=app_name),
                    MetadataEntry(key="namespace", value=namespace),
                ),
            )
        except (SregymAdapterError, ValueError) as exc:
            raise SregymAdapterError("SREGym application payload is invalid") from exc
        self._issued_identity = (task.session_id, task.task_id, task.phase)
        return task

    async def submit(self, submission: EvaluationResult) -> None:
        if self._issued_identity is None:
            raise SregymAdapterError("no SREGym task is awaiting submission")
        identity = (submission.session_id, submission.task_id, submission.phase)
        if identity != self._issued_identity:
            raise SregymAdapterError("submission does not match the issued SREGym task")
        try:
            async with self._http.stream(
                "POST",
                f"{self._config.conductor_url.rstrip('/')}/submit",
                json={"solution": submission.summary},
                timeout=self._config.request_timeout_seconds,
            ) as response:
                _raise_for_status(response, operation="submit")
                await _read_bounded_body(
                    response,
                    operation="submit",
                    max_bytes=self._config.max_response_bytes,
                )
        except httpx.HTTPError as exc:
            raise SregymAdapterError(f"SREGym submit request failed: {exc}") from exc
        self._submitted_stage = submission.phase
        self._issued_identity = None

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _wait_for_next_stage(self) -> str:
        deadline = asyncio.get_running_loop().time() + self._config.stage_timeout_seconds
        while True:
            stage = await self._read_stage()
            if stage in _TERMINAL_STAGES:
                return stage
            if stage in _TASK_STAGES and stage != self._submitted_stage:
                return stage
            if asyncio.get_running_loop().time() >= deadline:
                raise SregymAdapterError("timed out waiting for the next SREGym stage")
            await asyncio.sleep(self._config.poll_interval_seconds)

    async def _read_stage(self) -> str:
        payload = await self._get_json("/status")
        stage = _required_text(payload, "stage")
        if stage not in _TASK_STAGES | _TERMINAL_STAGES:
            raise SregymAdapterError(f"unsupported SREGym stage {stage!r}")
        return stage

    async def _get_json(self, path: str) -> Mapping[str, Any]:
        try:
            async with self._http.stream(
                "GET",
                f"{self._config.conductor_url.rstrip('/')}{path}",
                timeout=self._config.request_timeout_seconds,
            ) as response:
                _raise_for_status(response, operation=path)
                body = await _read_bounded_body(
                    response,
                    operation=path,
                    max_bytes=self._config.max_response_bytes,
                )
        except httpx.HTTPError as exc:
            raise SregymAdapterError(f"SREGym request {path!r} failed: {exc}") from exc
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise SregymAdapterError(f"SREGym response for {path!r} is not JSON") from exc
        if not isinstance(payload, Mapping):
            raise SregymAdapterError(f"SREGym response for {path!r} is not an object")
        return payload


async def _read_bounded_body(
    response: httpx.Response,
    *,
    operation: str,
    max_bytes: int,
) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > max_bytes:
            raise SregymAdapterError(
                f"SREGym response for {operation!r} is over the {max_bytes}-byte cap"
            )
        body.extend(chunk)
    return bytes(body)


def _required_text(
    payload: Mapping[str, Any],
    key: str,
    *,
    max_length: int = 256,
) -> str:
    value = payload.get(key)
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > max_length
        or any(ord(char) < 32 for char in value)
    ):
        raise SregymAdapterError(f"SREGym response field {key!r} MUST be non-empty text")
    return value


def _raise_for_status(response: httpx.Response, *, operation: str) -> None:
    if response.is_success:
        return
    raise SregymAdapterError(f"SREGym {operation} returned HTTP {response.status_code}")


def _objective(stage: str, *, app_name: str, descriptions: str) -> str:
    if stage == "diagnosis":
        return (
            f"Diagnose the production issue affecting {app_name}. "
            f"Use bounded evidence and identify the root cause. Context: {descriptions}"
        )
    if stage == "mitigation":
        return (
            f"Propose and verify a governed recovery for {app_name}. "
            "Any mutation must use the normal FDAI risk and execution path."
        )
    return f"Verify that {app_name} is healthy and summarize the resolution evidence."


__all__ = ["SregymAdapter", "SregymAdapterConfig", "SregymAdapterError"]
