"""Azure Monitor Perf adapter for bounded VM process CPU evidence."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.core.ontology_platform.vm_process_evidence import (
    VmProcessCpuCollection,
    VmProcessCpuObservation,
)
from fdai.delivery.azure.log_query import AzureLogAnalyticsQueryProvider
from fdai.shared.providers.observation import LogQueryError

_MAX_PROCESSES = 32


class AzureVmProcessCpuReader:
    """Read top process CPU aggregates from the allowlisted Azure Monitor Perf schema."""

    def __init__(
        self,
        provider: AzureLogAnalyticsQueryProvider,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        self._now = now or (lambda: datetime.now(UTC))

    async def read_process_cpu(
        self,
        *,
        resource_id: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> VmProcessCpuCollection:
        """Return exact-window process aggregates or explicit unavailable evidence."""

        if not resource_id.strip() or len(resource_id) > 1024:
            raise ValueError("VM process resource_id MUST be bounded and non-empty")
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("VM process query window MUST be aware and positive")
        if not 1 <= limit <= _MAX_PROCESSES:
            raise ValueError("VM process query limit MUST be in [1, 32]")
        attempt_ref = _evidence_ref("attempt", resource_id, start, end)
        try:
            result = await self._provider.query_log(
                query=_process_cpu_kql(resource_id=resource_id, start=start, end=end),
                window=_duration(end - start),
                max_rows=limit,
            )
            observations = tuple(
                sorted(
                    (_observation(row, start=start, end=end) for row in result.rows),
                    key=lambda item: (
                        -item.average_cpu_percent,
                        -item.maximum_cpu_percent,
                        item.process_name.casefold(),
                    ),
                )
            )
        except LogQueryError:
            return VmProcessCpuCollection(
                resource_id=resource_id,
                start=start,
                end=end,
                observed_at=self._now(),
                observations=(),
                complete=False,
                truncated=False,
                limitation="provider_unavailable",
                attempt_ref=attempt_ref,
            )
        except (TypeError, ValueError):
            return VmProcessCpuCollection(
                resource_id=resource_id,
                start=start,
                end=end,
                observed_at=self._now(),
                observations=(),
                complete=False,
                truncated=False,
                limitation="provider_invalid",
                attempt_ref=attempt_ref,
            )
        provider_gap = not observations and not result.truncated
        return VmProcessCpuCollection(
            resource_id=resource_id,
            start=start,
            end=end,
            observed_at=self._now(),
            observations=observations,
            complete=not result.truncated and not provider_gap,
            truncated=result.truncated,
            limitation=(
                "sample_limit" if result.truncated else "provider_gap" if provider_gap else None
            ),
            attempt_ref=attempt_ref,
        )


def _process_cpu_kql(*, resource_id: str, start: datetime, end: datetime) -> str:
    return (
        "Perf "
        f"| where TimeGenerated between (datetime({start.isoformat()}) .. "
        f"datetime({end.isoformat()})) "
        f"| where _ResourceId =~ {_kql_string(resource_id)} "
        '| where ObjectName in~ ("Process", "Process Information") '
        '| where CounterName == "% Processor Time" '
        '| where InstanceName != "_Total" and isnotempty(InstanceName) '
        "| summarize average_cpu_percent = avg(CounterValue), "
        "maximum_cpu_percent = max(CounterValue), sample_count = count(), "
        "first_observed_at = min(TimeGenerated), last_observed_at = max(TimeGenerated) "
        "by process_name = InstanceName, resource_id = tolower(_ResourceId) "
        "| order by average_cpu_percent desc, maximum_cpu_percent desc, process_name asc"
    )


def _observation(
    row: Mapping[str, Any],
    *,
    start: datetime,
    end: datetime,
) -> VmProcessCpuObservation:
    resource_id = _text(row, "resource_id")
    process_name = _text(row, "process_name")
    average = _number(row, "average_cpu_percent")
    maximum = _number(row, "maximum_cpu_percent")
    sample_count = _integer(row, "sample_count")
    first = _timestamp(row, "first_observed_at")
    last = _timestamp(row, "last_observed_at")
    return VmProcessCpuObservation(
        resource_id=resource_id,
        process_name=process_name,
        average_cpu_percent=average,
        maximum_cpu_percent=maximum,
        sample_count=sample_count,
        first_observed_at=first,
        last_observed_at=last,
        evidence_ref=_evidence_ref(process_name, resource_id, start, end),
    )


def _text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Azure VM process row is missing {key}")
    return value.strip()


def _number(row: Mapping[str, Any], key: str) -> float:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Azure VM process row has invalid {key}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Azure VM process row has non-finite {key}")
    return number


def _integer(row: Mapping[str, Any], key: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Azure VM process row has invalid {key}")
    return value


def _timestamp(row: Mapping[str, Any], key: str) -> datetime:
    value = _text(row, key)
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError(f"Azure VM process row has naive {key}")
    return timestamp


def _kql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _duration(value: timedelta) -> str:
    return f"PT{value.total_seconds():.3f}S"


def _evidence_ref(label: str, resource_id: str, start: datetime, end: datetime) -> str:
    payload = f"{label}\0{resource_id.casefold()}\0{start.isoformat()}\0{end.isoformat()}"
    return f"azure-monitor-perf:{hashlib.sha256(payload.encode()).hexdigest()}"


__all__ = ["AzureVmProcessCpuReader"]
