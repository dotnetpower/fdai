"""Read the canonical consumed canary audit without publishing a probe or granting authority."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.self_health import (
    OperationalStateFieldName,
    OperationalStateFieldStatus,
    OperationalStateFieldV1,
    SelfHealthSignalName,
)
from psycopg import Error as DatabaseError

from fdai.delivery.persistence.postgres import PostgresStateStore
from fdai.shared.providers.self_health import (
    SelfHealthExporterUnavailableError,
    SelfHealthExportSample,
)
from fdai.shared.providers.state_store import StateStore, StateStoreAuditReader

_ACTION = "control_loop.canary"
_ACTOR = "fdai.canary-job"


@dataclass(frozen=True, slots=True)
class ConsumedCanaryReceipt:
    recorded_at: datetime
    digest: str


@dataclass(slots=True)
class ConsumedCanarySource:
    """One audit read per collection time, shared by the three canary projections.

    The database belongs to this installation, not this process or replica. Only a
    consumed canonical no-op is evidence; publication and startup Kafka probes aren't.
    """

    store: StateStore
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _collected_at: datetime | None = field(default=None, init=False)
    _receipt: ConsumedCanaryReceipt | None = field(default=None, init=False)
    _reason: str | None = field(default=None, init=False)

    async def read(self, *, now: datetime) -> ConsumedCanaryReceipt:
        async with self._lock:
            if self._collected_at != now:
                self._receipt = None
                self._reason = None
                try:
                    raw = await self._latest_entry()
                    if raw is None:
                        raise SelfHealthExporterUnavailableError(reason="source_missing")
                    self._receipt = _receipt(raw, now=now)
                except asyncio.CancelledError:
                    # Other projections must not retry this abandoned collection.
                    self._reason = "source_incomplete"
                    self._collected_at = now
                    raise
                except (OSError, DatabaseError):
                    self._reason = "source_unreachable"
                except SelfHealthExporterUnavailableError as exc:
                    self._reason = exc.reason
                self._collected_at = now
            if self._reason is not None:
                raise SelfHealthExporterUnavailableError(reason=self._reason)
            return cast(ConsumedCanaryReceipt, self._receipt)

    async def _latest_entry(self) -> Mapping[str, Any] | None:
        if isinstance(self.store, PostgresStateStore):
            async with self.store._connection() as conn:
                async with conn.transaction():
                    await conn.execute("SET TRANSACTION READ ONLY")
                    await self.store._set_statement_timeout(conn)
                    cursor = await conn.execute(
                        """
                        SELECT entry FROM audit_log
                         WHERE action_kind = %s
                         ORDER BY seq DESC LIMIT 1
                        """,
                        (_ACTION,),
                    )
                    row = await cursor.fetchone()
            if row is None:
                return None
            raw = row.get("entry")
            if not isinstance(raw, Mapping):
                raise SelfHealthExporterUnavailableError(reason="source_malformed")
            return raw
        if isinstance(self.store, StateStoreAuditReader):
            rows, truncated = await self.store.read_audit_entries(limit=512)
            if truncated:
                # An oldest-first prefix cannot establish the latest consumed canary.
                raise SelfHealthExporterUnavailableError(reason="source_incomplete")
            return next((row for row in reversed(rows) if row.get("action_kind") == _ACTION), None)
        raise SelfHealthExporterUnavailableError(reason="source_incomplete")


def _receipt(raw: Mapping[str, Any], *, now: datetime) -> ConsumedCanaryReceipt:
    correlation = raw.get("correlation_id")
    if not isinstance(correlation, str) or not correlation.startswith("canary:"):
        raise SelfHealthExporterUnavailableError(reason="source_malformed")
    slot = correlation.removeprefix("canary:")
    expected = {
        "actor": _ACTOR,
        "action_kind": _ACTION,
        "event_id": str(uuid5(NAMESPACE_URL, f"fdai.canary://{slot}")),
        "idempotency_key": correlation,
        "mode": "shadow",
        "tier": "canary",
        "decision": "no-op",
        "outcome": "success",
    }
    if (
        not slot
        or slot != slot.strip()
        or len(slot) > 100
        or any(raw.get(key) != value for key, value in expected.items())
    ):
        raise SelfHealthExporterUnavailableError(reason="source_malformed")
    latency = raw.get("latency_ms")
    if type(latency) is not int or latency < 0:
        raise SelfHealthExporterUnavailableError(reason="source_malformed")
    try:
        detected_at = datetime.fromisoformat(raw["detected_at"])
        recorded_at = datetime.fromisoformat(raw["recorded_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SelfHealthExporterUnavailableError(reason="source_malformed") from exc
    if (
        detected_at.utcoffset() is None
        or recorded_at.utcoffset() is None
        or recorded_at < detected_at
        or latency != int((recorded_at - detected_at).total_seconds() * 1000)
    ):
        raise SelfHealthExporterUnavailableError(reason="source_malformed")
    if recorded_at > now:
        raise SelfHealthExporterUnavailableError(reason="source_from_future")
    return ConsumedCanaryReceipt(
        recorded_at=recorded_at,
        digest=canonical_digest(
            {
                **expected,
                "correlation_id": correlation,
                "detected_at": detected_at.isoformat(),
                "recorded_at": recorded_at.isoformat(),
                "latency_ms": latency,
            }
        ),
    )


@dataclass(frozen=True, slots=True)
class CanarySelfHealthExporter:
    source: ConsumedCanarySource
    signal: SelfHealthSignalName
    metric: str
    exporter_id: str

    async def observe(self, *, now: datetime) -> SelfHealthExportSample:
        receipt = await self.source.read(now=now)
        age_signal = self.signal is SelfHealthSignalName.TIME_SINCE_LAST_SUCCESSFUL_CANARY
        return SelfHealthExportSample(
            signal=self.signal,
            value=(
                Decimal(str((now - receipt.recorded_at).total_seconds()))
                if age_signal
                else Decimal(1)
            ),
            observed_at=now if age_signal else receipt.recorded_at,
            source=self.exporter_id,
        )


@dataclass(frozen=True, slots=True)
class CanaryStateExporter:
    source: ConsumedCanarySource
    field_name: OperationalStateFieldName = OperationalStateFieldName.CANARY
    exporter_id: str = "audit-log:canary:last-success-age"
    maximum_age_seconds: int = 60

    async def observe(self, *, now: datetime) -> OperationalStateFieldV1:
        receipt = await self.source.read(now=now)
        return OperationalStateFieldV1(
            name=self.field_name,
            status=OperationalStateFieldStatus.AVAILABLE,
            value_digest=canonical_digest(
                {
                    "consumed_receipt_digest": receipt.digest,
                    "last_success_at": receipt.recorded_at.isoformat(),
                    "age_seconds": str((now - receipt.recorded_at).total_seconds()),
                }
            ),
            source=self.exporter_id,
            observed_at=now,
            maximum_age_seconds=self.maximum_age_seconds,
            fresh=True,
            reason="current",
        )
