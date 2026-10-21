"""Elapsed age from independently read consumed-canary audits, never publish acceptance."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable
from uuid import NAMESPACE_URL, uuid5

from fdai_service_contracts.self_health import SelfHealthSignalName
from psycopg import Error as DatabaseError

from fdai.shared.providers.audit_hash import next_hash
from fdai.shared.providers.self_health import (
    SelfHealthExporterUnavailableError,
    SelfHealthExportSample,
)
from fdai.shared.providers.state_store import StateStore


@runtime_checkable
class _LatestCanaryReader(Protocol):
    async def read_latest_consumed_canary(self) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class ConsumedCanaryAgeExporter:
    store: StateStore
    metric: str
    signal: SelfHealthSignalName = SelfHealthSignalName.TIME_SINCE_LAST_SUCCESSFUL_CANARY
    exporter_id: str = "state-store:consumed-canary:age"

    async def observe(self, *, now: datetime) -> SelfHealthExportSample:
        if now.utcoffset() is None:
            raise ValueError("canary age measurement requires an aware timestamp")
        if not isinstance(self.store, _LatestCanaryReader):
            raise SelfHealthExporterUnavailableError(reason="source_incomplete")
        try:
            row = await self.store.read_latest_consumed_canary()
        except (OSError, DatabaseError) as exc:
            raise SelfHealthExporterUnavailableError(reason="source_unreachable") from exc
        if row is None:
            raise SelfHealthExporterUnavailableError(reason="source_missing")
        try:
            recorded_at = _validated_recorded_at(row)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise SelfHealthExporterUnavailableError(reason="source_malformed") from exc
        if recorded_at > now:
            raise SelfHealthExporterUnavailableError(reason="source_from_future")
        elapsed = now.astimezone(UTC) - recorded_at
        seconds = elapsed.days * 86_400 + elapsed.seconds
        return SelfHealthExportSample(
            signal=self.signal,
            value=Decimal(f"{seconds}.{elapsed.microseconds:06d}"),
            observed_at=now,
            source=self.exporter_id,
        )


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        raise ValueError("canary timestamp is malformed")
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("canary timestamp is naive")
    return result.astimezone(UTC)


def _validated_recorded_at(row: Mapping[str, Any]) -> datetime:
    entry = validated_canary_audit(row)
    if entry["action_kind"] != "control_loop.canary" or entry["outcome"] != "success":
        raise ValueError("canary age requires a canonical success")
    recorded_at = _timestamp(entry["recorded_at"])
    detected_at = _timestamp(entry["detected_at"])
    latency = entry["latency_ms"]
    if type(latency) is not int or latency != int(
        (recorded_at - detected_at).total_seconds() * 1000
    ):
        raise ValueError("canary audit timing is inconsistent")
    return recorded_at


def validated_canary_audit(row: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate a bounded canonical success or consumed-attempt audit envelope."""
    entry = row["entry"]
    if not isinstance(entry, Mapping):
        raise ValueError("canary audit entry is not an object")
    if type(row["seq"]) is not int or row["seq"] < 1:
        raise ValueError("canary audit sequence is malformed")
    expected = {
        "actor": "fdai.canary-job",
        "tier": "canary",
        "decision": "no-op",
    }
    if any(entry.get(key) != value for key, value in expected.items()):
        raise ValueError("canary audit identity is malformed")
    if (entry.get("action_kind"), entry.get("outcome")) not in {
        ("control_loop.canary", "success"),
        ("control_loop.canary.attempt", "started"),
        ("control_loop.canary.attempt", "failure"),
        ("control_loop.canary.attempt", "cancelled"),
    }:
        raise ValueError("canary audit phase is malformed")
    for key in ("actor", "action_kind", "event_id", "correlation_id", "mode"):
        if row[key] != entry.get(key):
            raise ValueError("canary audit columns conflict with its entry")
    if entry["mode"] not in {"shadow", "enforce"}:
        raise ValueError("canary audit mode is malformed")
    correlation = entry["correlation_id"]
    if (
        not isinstance(correlation, str)
        or not correlation.startswith("canary:")
        or not 1 <= len(correlation[7:]) <= 100
        or correlation[7:] != correlation[7:].strip()
        or entry["idempotency_key"] != correlation
        or entry["event_id"] != str(uuid5(NAMESPACE_URL, f"fdai.canary://{correlation[7:]}"))
    ):
        raise ValueError("canary event binding is malformed")
    previous, digest = row["previous_hash"], row["entry_hash"]
    if (
        not isinstance(previous, str)
        or len(previous) != 64
        or any(character not in "0123456789abcdef" for character in previous)
        or not isinstance(digest, str)
        or digest != next_hash(previous, entry)
    ):
        raise ValueError("canary audit hash is malformed")
    recorded_at = _timestamp(entry["recorded_at"])
    detected_at = _timestamp(entry["detected_at"])
    if detected_at > recorded_at:
        raise ValueError("canary audit timing is inconsistent")
    return entry
