"""Concrete bounded startup probes behind provider-neutral seams."""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import ssl
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fdai.core.readiness import ProbeStatus, StartupProbeResult
from fdai.delivery.startup_model_probe import (
    CapabilityProofStartupProbe,
    CrossCheckModelStartupProbe,
    EmbeddingModel,
    EmbeddingStartupProbe,
    StreamingModelStartupProbe,
)
from fdai.shared.providers.event_bus import EventBus, EventEnvelope
from fdai.shared.providers.startup_probe import StartupProbeRequest
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _result(
    probe_id: str,
    started_at: float,
    *,
    evidence: Mapping[str, bool | float | int | str] | None = None,
) -> StartupProbeResult:
    observed_at = _utc_now()
    return StartupProbeResult(
        probe_id=probe_id,
        status=ProbeStatus.PASSED,
        observed_at=observed_at,
        expires_at=observed_at + timedelta(minutes=5),
        latency_ms=(perf_counter() - started_at) * 1000,
        evidence=dict(evidence or {}),
    )


@dataclass(frozen=True, slots=True)
class DestinationTarget:
    """One exact enabled runtime destination, never serialized into evidence."""

    host: str
    port: int
    tls_server_name: str
    auth_audience: str

    def __post_init__(self) -> None:
        if not self.host or not self.tls_server_name or not self.auth_audience:
            raise ValueError("startup destination fields MUST NOT be empty")
        if not 1 <= self.port <= 65_535:
            raise ValueError("startup destination port MUST be between 1 and 65535")


class DestinationChainProbe:
    """Prove DNS, TCP, TLS, auth, and one bounded protocol operation."""

    def __init__(
        self,
        *,
        probe_id: str,
        target: DestinationTarget,
        identity: WorkloadIdentity,
        protocol_operation: Callable[[], Awaitable[None]],
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.probe_id = probe_id
        self._target = target
        self._identity = identity
        self._protocol_operation = protocol_operation
        self._ssl_context = ssl_context or ssl.create_default_context()

    async def run(self, request: StartupProbeRequest) -> StartupProbeResult:
        started_at = perf_counter()
        loop = asyncio.get_running_loop()
        addresses = await loop.getaddrinfo(
            self._target.host,
            self._target.port,
            type=socket.SOCK_STREAM,
        )
        if not addresses:
            raise RuntimeError("destination DNS returned no addresses")
        _, writer = await asyncio.open_connection(
            self._target.host,
            self._target.port,
            ssl=self._ssl_context,
            server_hostname=self._target.tls_server_name,
        )
        writer.close()
        await writer.wait_closed()
        token = await self._identity.get_token(self._target.auth_audience)
        if token.audience != self._target.auth_audience or token.expires_at <= _utc_now():
            raise RuntimeError("destination token is invalid")
        await self._protocol_operation()
        return _result(
            self.probe_id,
            started_at,
            evidence={"dns": True, "tcp": True, "tls": True, "auth": True, "protocol": True},
        )


class StateStoreStartupProbe:
    """Prove PostgreSQL-backed state access with a read-only operation."""

    def __init__(self, *, probe_id: str, state_store: StateStore) -> None:
        self.probe_id = probe_id
        self._state_store = state_store

    async def run(self, request: StartupProbeRequest) -> StartupProbeResult:
        started_at = perf_counter()
        await self._state_store.read_state("runtime:startup-readiness:probe")
        return _result(self.probe_id, started_at, evidence={"read": True})


class StaticStartupProbe:
    """Record that an already-completed static startup boundary succeeded."""

    def __init__(self, *, probe_id: str, evidence_key: str) -> None:
        self.probe_id = probe_id
        self._evidence_key = evidence_key

    async def run(self, request: StartupProbeRequest) -> StartupProbeResult:
        return _result(self.probe_id, perf_counter(), evidence={self._evidence_key: True})


class EnvironmentInjectionStartupProbe:
    """Verify required environment-backed secret references without reading values."""

    def __init__(
        self,
        *,
        probe_id: str,
        environment: Mapping[str, str],
        required_names: tuple[str, ...],
    ) -> None:
        self.probe_id = probe_id
        self._environment = environment
        self._required_names = required_names

    async def run(self, request: StartupProbeRequest) -> StartupProbeResult:
        started_at = perf_counter()
        missing = [
            name for name in self._required_names if not self._environment.get(name, "").strip()
        ]
        if missing:
            raise RuntimeError("required startup secret injection is unavailable")
        return _result(
            self.probe_id,
            started_at,
            evidence={"required_reference_count": len(self._required_names)},
        )


class WorkloadIdentityStartupProbe:
    """Prove one audience-scoped token without retaining token material."""

    def __init__(
        self,
        *,
        probe_id: str,
        identity: WorkloadIdentity,
        audience: str,
    ) -> None:
        if not audience:
            raise ValueError("startup identity audience MUST NOT be empty")
        self.probe_id = probe_id
        self._identity = identity
        self._audience = audience

    async def run(self, request: StartupProbeRequest) -> StartupProbeResult:
        started_at = perf_counter()
        token = await self._identity.get_token(self._audience)
        if token.audience != self._audience or token.expires_at <= _utc_now():
            raise RuntimeError("startup identity token is invalid")
        return _result(self.probe_id, started_at, evidence={"audience_scoped": True})


class OpaCompileStartupProbe:
    """Compile the complete policy tree without evaluating a resource."""

    def __init__(
        self,
        *,
        probe_id: str,
        policies_root: Path,
        opa_binary: str = "opa",
    ) -> None:
        if not policies_root.is_dir():
            raise ValueError("startup OPA policies root MUST be an existing directory")
        resolved = shutil.which(opa_binary)
        self.probe_id = probe_id
        self._policies_root = policies_root
        self._opa_binary = resolved

    async def run(self, request: StartupProbeRequest) -> StartupProbeResult:
        started_at = perf_counter()
        if self._opa_binary is None:
            raise RuntimeError("OPA binary is unavailable")
        process = await asyncio.create_subprocess_exec(
            self._opa_binary,
            "check",
            str(self._policies_root),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env={"PATH": os.environ.get("PATH", "")},
        )
        if await process.wait() != 0:
            raise RuntimeError("OPA policy compile failed")
        return _result(self.probe_id, started_at, evidence={"compiled": True})


class KillSwitchStartupProbe:
    """Validate the durable kill-switch record through its owning refresher."""

    def __init__(
        self,
        *,
        probe_id: str,
        refresh: Callable[[], Awaitable[None]],
    ) -> None:
        self.probe_id = probe_id
        self._refresh = refresh

    async def run(self, request: StartupProbeRequest) -> StartupProbeResult:
        started_at = perf_counter()
        await self._refresh()
        return _result(self.probe_id, started_at, evidence={"read": True})


class AuditStartupProbe:
    """Append one bounded synthetic audit record to prove audit durability."""

    def __init__(self, *, probe_id: str, state_store: StateStore) -> None:
        self.probe_id = probe_id
        self._state_store = state_store

    async def run(self, request: StartupProbeRequest) -> StartupProbeResult:
        if not request.synthetic_scope:
            raise RuntimeError("audit startup probe requires synthetic scope")
        started_at = perf_counter()
        probe_run = uuid4().hex
        await self._state_store.append_audit_entry(
            {
                "kind": "startup_readiness.audit_probe",
                "event_id": f"startup-audit-{probe_run}",
                "correlation_id": None,
                "tier": "t0",
                "decision": "probe",
                "idempotency_key": f"startup-audit:{probe_run}",
                "actor_identity": "runtime.startup",
                "timestamp": _utc_now().isoformat(),
                "mode": "shadow",
                "rollback_reference": None,
            }
        )
        return _result(self.probe_id, started_at, evidence={"append": True})


class EventBusRoundTripStartupProbe:
    """Round-trip one dedicated synthetic record through the configured bus."""

    def __init__(
        self,
        *,
        probe_id: str,
        event_bus: EventBus,
        topic: str,
        consumer_settle_seconds: float = 0.5,
    ) -> None:
        if not topic:
            raise ValueError("startup event-bus probe topic MUST NOT be empty")
        if consumer_settle_seconds < 0:
            raise ValueError("consumer settle seconds MUST be >= 0")
        self.probe_id = probe_id
        self._event_bus = event_bus
        self._topic = topic
        self._consumer_settle_seconds = consumer_settle_seconds

    async def run(self, request: StartupProbeRequest) -> StartupProbeResult:
        if not request.synthetic_scope:
            raise RuntimeError("event-bus round-trip requires synthetic scope")
        started_at = perf_counter()
        key = f"startup-{uuid4().hex}"
        group_id = f"startup-probe-{uuid4().hex}"
        iterator = self._event_bus.subscribe(self._topic, group_id)

        async def receive() -> EventEnvelope:
            return await anext(iterator)

        receive_task: asyncio.Task[EventEnvelope] = asyncio.create_task(receive())
        try:
            if self._consumer_settle_seconds:
                await asyncio.sleep(self._consumer_settle_seconds)
            await self._event_bus.publish(
                self._topic,
                key,
                {"kind": "startup_probe", "probe_id": self.probe_id},
            )
            envelope = await receive_task
        finally:
            if not receive_task.done():
                receive_task.cancel()
                await asyncio.gather(receive_task, return_exceptions=True)
            close = getattr(iterator, "aclose", None)
            if callable(close):
                await close()
        if envelope.key != key or envelope.payload.get("probe_id") != self.probe_id:
            raise RuntimeError("event-bus startup round-trip payload mismatch")
        return _result(self.probe_id, started_at, evidence={"round_trip": True})


__all__ = [
    "AuditStartupProbe",
    "CapabilityProofStartupProbe",
    "CrossCheckModelStartupProbe",
    "DestinationChainProbe",
    "DestinationTarget",
    "EnvironmentInjectionStartupProbe",
    "EmbeddingModel",
    "EmbeddingStartupProbe",
    "EventBusRoundTripStartupProbe",
    "KillSwitchStartupProbe",
    "OpaCompileStartupProbe",
    "StateStoreStartupProbe",
    "StaticStartupProbe",
    "StreamingModelStartupProbe",
    "WorkloadIdentityStartupProbe",
]
