"""Azure trace-continuity source normalization and fail-closed behavior."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from fdai.delivery.azure.trace_continuity import (
    TRACE_CONTINUITY_KQL,
    AzureTraceContinuitySource,
    TraceContinuitySourceError,
    TraceTopologyTarget,
)
from fdai.shared.providers.observation import LogQueryResult


class _LogProvider:
    def __init__(
        self,
        rows: tuple[Mapping[str, Any], ...],
        *,
        truncated: bool = False,
    ) -> None:
        self._result = LogQueryResult(rows=rows, truncated=truncated)
        self.calls: list[tuple[str, str, int]] = []

    async def query_log(
        self,
        *,
        query: str,
        window: str,
        max_rows: int = 100,
    ) -> LogQueryResult:
        self.calls.append((query, window, max_rows))
        return self._result


def _target() -> TraceTopologyTarget:
    return TraceTopologyTarget(
        topology_ref="synthetic-agent-request",
        resource_ref="trace-topology/synthetic-agent-request",
        expected_hops=("application", "agent", "api-gateway", "model-endpoint"),
    )


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "topology_ref": "synthetic-agent-request",
        "scenario_id": "scenario-001",
        "trace_id": "trace-a",
        "span_id": "span-a",
        "hop": "application",
        "sequence": 0,
        "observed_at": "2026-08-17T01:00:00Z",
        "completed": False,
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_collects_one_bounded_query_and_groups_completed_runs() -> None:
    provider = _LogProvider(
        (
            _row(),
            _row(span_id="span-b", hop="agent", sequence=1, completed=True),
            _row(topology_ref="another-topology", scenario_id="ignored"),
        )
    )
    source = AzureTraceContinuitySource(provider)

    observations = await source.collect(
        (_target(),),
        window_seconds=300,
        window_bucket="2026-08-17T01:00Z",
    )

    assert len(observations) == 1
    assert observations[0].completed is True
    assert tuple(span.hop for span in observations[0].spans) == ("application", "agent")
    assert observations[0].spans[0].evidence_ref == "appinsights:span-a"
    assert provider.calls == [(TRACE_CONTINUITY_KQL, "PT300S", 2_000)]
    assert "ItemId" not in TRACE_CONTINUITY_KQL
    assert "span_id = tostring(Id)" in TRACE_CONTINUITY_KQL


@pytest.mark.asyncio
async def test_empty_rows_are_not_inferred_as_a_failure() -> None:
    source = AzureTraceContinuitySource(_LogProvider(()))

    observations = await source.collect(
        (_target(),),
        window_seconds=300,
        window_bucket="2026-08-17T01:00Z",
    )

    assert observations == ()


@pytest.mark.asyncio
async def test_truncated_evidence_fails_closed() -> None:
    source = AzureTraceContinuitySource(_LogProvider((_row(),), truncated=True))

    with pytest.raises(TraceContinuitySourceError, match="truncated"):
        await source.collect(
            (_target(),),
            window_seconds=300,
            window_bucket="2026-08-17T01:00Z",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    (("sequence", "0"), ("completed", "true"), ("observed_at", "not-a-time")),
)
async def test_malformed_configured_rows_fail_closed(field: str, value: object) -> None:
    source = AzureTraceContinuitySource(_LogProvider((_row(**{field: value}),)))

    with pytest.raises(TraceContinuitySourceError, match=field):
        await source.collect(
            (_target(),),
            window_seconds=300,
            window_bucket="2026-08-17T01:00Z",
        )
