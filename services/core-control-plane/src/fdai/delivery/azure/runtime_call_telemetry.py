"""Read exact runtime-call identities from Azure Monitor without granting authority."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai.core.ontology_platform.runtime_call_telemetry import (
    AuthenticatedRuntimeCallContext,
    RuntimeCallTelemetryEnvelope,
)
from fdai.delivery.runtime_call_inventory import (
    RuntimeCallTelemetryBatch,
    RuntimeCallTelemetryRecord,
)
from fdai.shared.providers.observation import LogQueryProvider

_MAX_ROWS = 2_000

RUNTIME_CALL_TELEMETRY_KQL = """
union isfuzzy=true
    (AppRequests | project TimeGenerated, Id, Properties),
    (AppDependencies | project TimeGenerated, Id, Properties)
| extend
    caller_resource_id = tostring(Properties["fdai.runtime.caller_resource_id"]),
    target_resource_id = tostring(Properties["fdai.runtime.target_resource_id"])
| where isnotempty(caller_resource_id) and isnotempty(target_resource_id)
| project
    observed_at = TimeGenerated,
    observation_id = tostring(Id),
    caller_resource_id,
    target_resource_id
| order by observed_at asc, observation_id asc
""".strip()


class RuntimeCallTelemetryContextProvider(Protocol):
    """Supply independently authenticated context for one telemetry envelope."""

    async def context_for(
        self,
        envelope: RuntimeCallTelemetryEnvelope,
    ) -> AuthenticatedRuntimeCallContext: ...


class AzureRuntimeCallTelemetrySource:
    """Collect bounded caller and target identities from a configured log provider."""

    def __init__(
        self,
        *,
        provider: LogQueryProvider,
        context_provider: RuntimeCallTelemetryContextProvider,
        scope_ref: str,
        source_identity: str = "azure-monitor.runtime-calls",
        source_revision: str = "1.0.0",
        freshness_ceiling_seconds: int = 300,
        max_rows: int = _MAX_ROWS,
    ) -> None:
        if not 1 <= max_rows <= _MAX_ROWS:
            raise ValueError(f"runtime call telemetry max_rows MUST be in [1, {_MAX_ROWS}]")
        if not scope_ref.strip() or not source_identity.strip() or not source_revision.strip():
            raise ValueError("runtime call telemetry source identity fields MUST be non-empty")
        if freshness_ceiling_seconds < 1:
            raise ValueError("runtime call telemetry freshness ceiling MUST be positive")
        self._provider = provider
        self._context_provider = context_provider
        self._scope_ref = scope_ref
        self._source_identity = source_identity
        self._source_revision = source_revision
        self._freshness_ceiling_seconds = freshness_ceiling_seconds
        self._max_rows = max_rows

    async def collect(self, _observation: object) -> RuntimeCallTelemetryBatch:
        """Return a complete typed batch or explicit incomplete evidence."""

        recorded_at = datetime.now(UTC)
        result = await self._provider.query_log(
            query=RUNTIME_CALL_TELEMETRY_KQL,
            window=f"PT{self._freshness_ceiling_seconds}S",
            max_rows=self._max_rows,
        )
        if result.truncated:
            return RuntimeCallTelemetryBatch(
                records=(),
                observed_at=None,
                complete=False,
                reason="telemetry_incomplete",
            )
        records: list[RuntimeCallTelemetryRecord] = []
        observed_times: list[datetime] = []
        for row in result.rows:
            envelope = self._envelope(row, recorded_at=recorded_at)
            context = await self._context_provider.context_for(envelope)
            records.append(RuntimeCallTelemetryRecord(envelope, context))
            observed_times.append(envelope.observed_at)
        return RuntimeCallTelemetryBatch(
            records=tuple(records),
            observed_at=max(observed_times, default=recorded_at),
            complete=True,
        )

    def _envelope(
        self,
        row: Mapping[str, Any],
        *,
        recorded_at: datetime,
    ) -> RuntimeCallTelemetryEnvelope:
        observation_id = _required_text(row, "observation_id")
        caller = _required_text(row, "caller_resource_id")
        target = _required_text(row, "target_resource_id")
        observed_at = _required_datetime(row, "observed_at")
        return RuntimeCallTelemetryEnvelope(
            observation_id=observation_id,
            caller_resource_ids=(caller,),
            target_resource_ids=(target,),
            scope_ref=self._scope_ref,
            observed_at=observed_at,
            evidence_cutoff=observed_at,
            recorded_at=recorded_at,
            freshness_ceiling_seconds=self._freshness_ceiling_seconds,
            source_identity=self._source_identity,
            source_revision=self._source_revision,
            evidence_ref=f"runtime-call:{observation_id}",
        )


def _required_text(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"runtime call telemetry {field} MUST be bounded non-empty text")
    return value.strip()


def _required_datetime(row: Mapping[str, Any], field: str) -> datetime:
    value = row.get(field)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"runtime call telemetry {field} MUST be RFC 3339") from exc
    else:
        raise ValueError(f"runtime call telemetry {field} MUST be RFC 3339")
    if parsed.tzinfo is None:
        raise ValueError(f"runtime call telemetry {field} MUST be timezone-aware")
    return parsed


__all__ = [
    "AzureRuntimeCallTelemetrySource",
    "RUNTIME_CALL_TELEMETRY_KQL",
    "RuntimeCallTelemetryContextProvider",
]
