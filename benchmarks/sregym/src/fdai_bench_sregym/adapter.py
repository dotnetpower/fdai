"""SREGym conductor lifecycle adapter."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit

import httpx

from fdai.benchmarking import BenchmarkSubmission, BenchmarkTask
from fdai.benchmarking.adapter import BenchmarkAdapterError

_TERMINAL_STAGES: Final[frozenset[str]] = frozenset({"done", "tearing_down"})
_TASK_STAGES: Final[frozenset[str]] = frozenset({"diagnosis", "mitigation", "resolution"})
_PLAINTEXT_HOSTS: Final[frozenset[str]] = frozenset(
    {"127.0.0.1", "localhost", "host.docker.internal"}
)
_DEFAULT_MAX_RESPONSE_BYTES: Final[int] = 1_000_000


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
        if not self.artifact_id.strip() or any(ord(char) < 32 for char in self.artifact_id):
            raise ValueError("artifact_id MUST be a non-empty identifier")
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
    ) -> None:
        self._config = config
        self._http = http_client or httpx.AsyncClient()
        self._owns_http = http_client is None
        self._submitted_stage: str | None = None
        self._issued_identity: tuple[str, str, str] | None = None
        self._started = False

    async def start(self) -> None:
        await self._read_stage()
        self._started = True

    async def next_task(self) -> BenchmarkTask | None:
        if not self._started:
            raise BenchmarkAdapterError("SREGym adapter MUST be started before reading tasks")
        if self._issued_identity is not None:
            raise BenchmarkAdapterError("a SREGym task is already awaiting submission")
        stage = await self._wait_for_next_stage()
        if stage in _TERMINAL_STAGES:
            return None
        app = await self._get_json("/get_app")
        namespace = _required_text(app, "namespace")
        app_name = _required_text(app, "app_name")
        descriptions = _required_text(app, "descriptions")
        try:
            task = BenchmarkTask(
                run_id=self._config.artifact_id,
                task_id=self._config.artifact_id,
                stage=stage,
                objective=_objective(stage, app_name=app_name, descriptions=descriptions),
                target_ref=f"kubernetes.namespace/{namespace}",
                metadata={"application": app_name, "namespace": namespace},
            )
        except ValueError as exc:
            raise BenchmarkAdapterError("SREGym application payload is invalid") from exc
        self._issued_identity = (task.run_id, task.task_id, task.stage)
        return task

    async def submit(self, submission: BenchmarkSubmission) -> None:
        if self._issued_identity is None:
            raise BenchmarkAdapterError("no SREGym task is awaiting submission")
        identity = (submission.run_id, submission.task_id, submission.stage)
        if identity != self._issued_identity:
            raise BenchmarkAdapterError("submission does not match the issued SREGym task")
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
            raise BenchmarkAdapterError(f"SREGym submit request failed: {exc}") from exc
        self._submitted_stage = submission.stage
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
                raise BenchmarkAdapterError("timed out waiting for the next SREGym stage")
            await asyncio.sleep(self._config.poll_interval_seconds)

    async def _read_stage(self) -> str:
        payload = await self._get_json("/status")
        stage = _required_text(payload, "stage")
        if stage not in _TASK_STAGES | _TERMINAL_STAGES:
            raise BenchmarkAdapterError(f"unsupported SREGym stage {stage!r}")
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
            raise BenchmarkAdapterError(f"SREGym request {path!r} failed: {exc}") from exc
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise BenchmarkAdapterError(f"SREGym response for {path!r} is not JSON") from exc
        if not isinstance(payload, Mapping):
            raise BenchmarkAdapterError(f"SREGym response for {path!r} is not an object")
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
            raise BenchmarkAdapterError(
                f"SREGym response for {operation!r} is over the {max_bytes}-byte cap"
            )
        body.extend(chunk)
    return bytes(body)


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or any(ord(char) < 32 for char in value):
        raise BenchmarkAdapterError(f"SREGym response field {key!r} MUST be non-empty text")
    return value


def _raise_for_status(response: httpx.Response, *, operation: str) -> None:
    if response.is_success:
        return
    raise BenchmarkAdapterError(f"SREGym {operation} returned HTTP {response.status_code}")


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


__all__ = ["SregymAdapter", "SregymAdapterConfig"]
