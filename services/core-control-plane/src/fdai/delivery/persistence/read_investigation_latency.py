"""Durable bounded read-investigation latency samples over StateStore CAS."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai.shared.providers.read_investigation import ReadLatencySample, ReadToolId
from fdai.shared.providers.state_store import StateStore


class ReadLatencyStoreConflictError(RuntimeError):
    """The bounded CAS retry budget was exhausted."""


@dataclass(frozen=True, slots=True)
class StateStoreReadLatencyConfig:
    max_samples: int = 200
    retention_days: int = 30
    max_cas_attempts: int = 8

    def __post_init__(self) -> None:
        if not 20 <= self.max_samples <= 2_000:
            raise ValueError("max_samples MUST be in [20, 2000]")
        if not 1 <= self.retention_days <= 365:
            raise ValueError("retention_days MUST be in [1, 365]")
        if not 1 <= self.max_cas_attempts <= 32:
            raise ValueError("max_cas_attempts MUST be in [1, 32]")


class StateStoreReadLatencyProfileStore:
    """Persist one bounded rolling sample set per metric-safe dimension key."""

    def __init__(
        self,
        *,
        store: StateStore,
        config: StateStoreReadLatencyConfig | None = None,
    ) -> None:
        self._store = store
        self._config = config or StateStoreReadLatencyConfig()

    async def append(self, sample: ReadLatencySample) -> None:
        key = _key(sample.tool_id, sample.transport, sample.operation_class)
        for _ in range(self._config.max_cas_attempts):
            current = await self._store.read_state(key)
            if current is None:
                value = self._value(sample, revision=1, prior=())
                created = await self._store.write_state_with_audit_if_absent(
                    key,
                    value,
                    _audit(sample, revision=1),
                )
                if created:
                    return
                continue
            revision = _revision(current)
            prior = _samples(current, expected=sample)
            value = self._value(sample, revision=revision + 1, prior=prior)
            updated = await self._store.compare_and_set_state_with_audit(
                key,
                value,
                expected_revision=revision,
                audit_entry=_audit(sample, revision=revision + 1),
            )
            if updated:
                return
        raise ReadLatencyStoreConflictError("read latency sample CAS retries exhausted")

    async def recent(
        self,
        *,
        tool_id: ReadToolId,
        transport: str,
        operation_class: str,
        limit: int,
    ) -> tuple[ReadLatencySample, ...]:
        if not 1 <= limit <= self._config.max_samples:
            raise ValueError(f"limit MUST be in [1, {self._config.max_samples}]")
        current = await self._store.read_state(_key(tool_id, transport, operation_class))
        if current is None:
            return ()
        expected = ReadLatencySample(
            tool_id=tool_id,
            transport=transport,
            operation_class=operation_class,
            succeeded=True,
            queue_duration_ms=0,
            execution_duration_ms=0,
            recorded_at=datetime.now(UTC),
        )
        return tuple(reversed(_samples(current, expected=expected)[-limit:]))

    def _value(
        self,
        sample: ReadLatencySample,
        *,
        revision: int,
        prior: tuple[ReadLatencySample, ...],
    ) -> dict[str, object]:
        cutoff = sample.recorded_at - timedelta(days=self._config.retention_days)
        retained = [item for item in prior if item.recorded_at >= cutoff]
        retained.append(sample)
        retained.sort(key=lambda item: item.recorded_at)
        retained = retained[-self._config.max_samples :]
        return {
            "revision": revision,
            "tool_id": sample.tool_id.value,
            "transport": sample.transport,
            "operation_class": sample.operation_class,
            "samples": [_sample_dict(item) for item in retained],
            "updated_at": sample.recorded_at.isoformat(),
        }


def _samples(
    value: Mapping[str, object],
    *,
    expected: ReadLatencySample,
) -> tuple[ReadLatencySample, ...]:
    if (
        value.get("tool_id") != expected.tool_id.value
        or value.get("transport") != expected.transport
        or value.get("operation_class") != expected.operation_class
    ):
        raise ValueError("read latency profile dimensions do not match the state key")
    raw = value.get("samples")
    if not isinstance(raw, list):
        raise ValueError("read latency profile samples MUST be a list")
    samples: list[ReadLatencySample] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("read latency profile sample MUST be an object")
        samples.append(
            ReadLatencySample(
                tool_id=expected.tool_id,
                transport=expected.transport,
                operation_class=expected.operation_class,
                succeeded=bool(item.get("succeeded")),
                queue_duration_ms=_integer(item, "queue_duration_ms"),
                execution_duration_ms=_integer(item, "execution_duration_ms"),
                recorded_at=_timestamp(item.get("recorded_at")),
            )
        )
    return tuple(samples)


def _key(tool_id: ReadToolId, transport: str, operation_class: str) -> str:
    dimensions = f"{tool_id.value}:{transport}:{operation_class}"
    digest = hashlib.sha256(dimensions.encode()).hexdigest()
    return f"read-investigation-latency:sha256:{digest}"


def _revision(value: Mapping[str, object]) -> int:
    revision = value.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("read latency profile revision MUST be positive")
    return revision


def _integer(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ValueError(f"read latency sample {key} MUST be non-negative")
    return item


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("read latency sample recorded_at MUST be text")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("read latency sample recorded_at is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("read latency sample recorded_at MUST be timezone-aware")
    return parsed


def _sample_dict(sample: ReadLatencySample) -> dict[str, object]:
    return {
        "succeeded": sample.succeeded,
        "queue_duration_ms": sample.queue_duration_ms,
        "execution_duration_ms": sample.execution_duration_ms,
        "recorded_at": sample.recorded_at.isoformat(),
    }


def _audit(sample: ReadLatencySample, *, revision: int) -> dict[str, object]:
    return {
        "action_kind": "read-investigation.latency-recorded",
        "tool_id": sample.tool_id.value,
        "transport": sample.transport,
        "operation_class": sample.operation_class,
        "succeeded": sample.succeeded,
        "queue_duration_ms": sample.queue_duration_ms,
        "execution_duration_ms": sample.execution_duration_ms,
        "recorded_at": sample.recorded_at.isoformat(),
        "revision": revision,
    }


__all__ = [
    "ReadLatencyStoreConflictError",
    "StateStoreReadLatencyConfig",
    "StateStoreReadLatencyProfileStore",
]
