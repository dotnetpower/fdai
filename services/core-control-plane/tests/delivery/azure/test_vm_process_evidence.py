"""Azure Monitor VM process CPU evidence adapter tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.delivery.azure.vm_process_evidence import AzureVmProcessCpuReader
from fdai.shared.providers.observation import LogQueryError, LogQueryResult

NOW = datetime(2026, 8, 26, 5, 0, tzinfo=UTC)
START = NOW - timedelta(minutes=10)


class _Provider:
    def __init__(
        self,
        result: LogQueryResult | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.result = result or LogQueryResult(
            rows=(),
            truncated=False,
            scanned_records=0,
            metadata={},
        )
        self.error = error
        self.calls: list[tuple[str, str, int]] = []

    async def query_log(
        self,
        *,
        query: str,
        window: str,
        max_rows: int = 100,
    ) -> LogQueryResult:
        self.calls.append((query, window, max_rows))
        if self.error is not None:
            raise self.error
        return self.result


def _row(
    process_name: str,
    *,
    average: float,
    maximum: float,
) -> dict[str, object]:
    return {
        "resource_id": "resource-vm-example",
        "process_name": process_name,
        "average_cpu_percent": average,
        "maximum_cpu_percent": maximum,
        "sample_count": 10,
        "first_observed_at": START.isoformat(),
        "last_observed_at": NOW.isoformat(),
    }


async def test_reader_projects_ordered_process_cpu_and_exact_query_bounds() -> None:
    provider = _Provider(
        LogQueryResult(
            rows=(
                _row("sidecar-example", average=20.0, maximum=30.0),
                _row("worker-example", average=75.0, maximum=90.0),
            ),
            truncated=False,
            scanned_records=2,
            metadata={},
        )
    )
    reader = AzureVmProcessCpuReader(provider, now=lambda: NOW)  # type: ignore[arg-type]

    result = await reader.read_process_cpu(
        resource_id="resource-vm-example",
        start=START,
        end=NOW,
        limit=8,
    )

    assert tuple(item.process_name for item in result.observations) == (
        "worker-example",
        "sidecar-example",
    )
    assert result.complete is True
    query, window, limit = provider.calls[0]
    assert "Perf" in query
    assert "_ResourceId =~ 'resource-vm-example'" in query
    assert 'ObjectName in~ ("Process", "Process Information")' in query
    assert 'CounterName == "% Processor Time"' in query
    assert f"datetime({START.isoformat()})" in query
    assert f"datetime({NOW.isoformat()})" in query
    assert window == "PT600.000S"
    assert limit == 8


async def test_reader_preserves_sample_limit_as_incomplete() -> None:
    provider = _Provider(
        LogQueryResult(
            rows=(_row("worker-example", average=75.0, maximum=90.0),),
            truncated=True,
            scanned_records=9,
            metadata={},
        )
    )
    reader = AzureVmProcessCpuReader(provider, now=lambda: NOW)  # type: ignore[arg-type]

    result = await reader.read_process_cpu(
        resource_id="resource-vm-example",
        start=START,
        end=NOW,
        limit=8,
    )

    assert result.complete is False
    assert result.truncated is True
    assert result.limitation == "sample_limit"


async def test_reader_maps_provider_failure_to_explicit_unavailable() -> None:
    provider = _Provider(error=LogQueryError("unavailable"))
    reader = AzureVmProcessCpuReader(provider, now=lambda: NOW)  # type: ignore[arg-type]

    result = await reader.read_process_cpu(
        resource_id="resource-vm-example",
        start=START,
        end=NOW,
        limit=8,
    )

    assert result.observations == ()
    assert result.complete is False
    assert result.limitation == "provider_unavailable"


async def test_reader_maps_empty_counter_window_to_provider_gap() -> None:
    reader = AzureVmProcessCpuReader(_Provider(), now=lambda: NOW)  # type: ignore[arg-type]

    result = await reader.read_process_cpu(
        resource_id="resource-vm-example",
        start=START,
        end=NOW,
        limit=8,
    )

    assert result.observations == ()
    assert result.complete is False
    assert result.limitation == "provider_gap"


async def test_reader_maps_malformed_rows_to_explicit_invalid() -> None:
    provider = _Provider(
        LogQueryResult(
            rows=(_row("worker-example", average=-1.0, maximum=90.0),),
            truncated=False,
            scanned_records=1,
            metadata={},
        )
    )
    reader = AzureVmProcessCpuReader(provider, now=lambda: NOW)  # type: ignore[arg-type]

    result = await reader.read_process_cpu(
        resource_id="resource-vm-example",
        start=START,
        end=NOW,
        limit=8,
    )

    assert result.observations == ()
    assert result.complete is False
    assert result.limitation == "provider_invalid"
