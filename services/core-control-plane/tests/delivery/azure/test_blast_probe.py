"""Azure Monitor live blast probe adapter tests."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.delivery.azure.blast_probe import (
    AzureMonitorBlastProbe,
    AzureMonitorProbeDefinition,
    azure_monitor_probe_definitions,
)
from fdai.rule_catalog.schema.probe import load_probe_catalog
from fdai.shared.providers.blast_probe import (
    BlastProbeConfigError,
    BlastProbeTimeoutError,
    ProbeQuery,
    ProbeVerdict,
)
from fdai.shared.providers.metric import MetricPoint, MetricQuery, StaticMetricProvider

_NOW = datetime(2026, 8, 29, 1, tzinfo=UTC)
_ROOT = Path(__file__).resolve().parents[5]


def _definition() -> AzureMonitorProbeDefinition:
    return AzureMonitorProbeDefinition(
        probe_id="vm_traffic_last_5m",
        metric_name="Network In Total",
        aggregation="p95",
        window_minutes=5,
        timeout_seconds=5,
        result_field="result_bytes",
        quiet_below=1_000_000,
        active_below=100_000_000,
    )


def _probe(values: list[float]) -> AzureMonitorBlastProbe:
    samples = [
        MetricPoint(
            metric_name="Network In Total",
            at=_NOW - timedelta(minutes=1),
            value=value,
            labels={"resource_id": "resource-1"},
        )
        for value in values
    ]
    return AzureMonitorBlastProbe(
        metric_provider=StaticMetricProvider(samples),
        definitions=(_definition(),),
        clock=lambda: _NOW,
    )


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([10.0, 20.0], ProbeVerdict.QUIET),
        ([2_000_000.0], ProbeVerdict.ACTIVE),
        ([200_000_000.0], ProbeVerdict.OVERLOADED),
    ],
)
async def test_probe_classifies_reviewed_thresholds(
    values: list[float],
    expected: ProbeVerdict,
) -> None:
    result = await _probe(values).measure(
        ProbeQuery(
            probe_id="vm_traffic_last_5m",
            target_ref="resource-1",
            deadline_seconds=1,
        )
    )

    assert result.verdict is expected
    assert result.degraded is False
    assert result.metrics["result_bytes"] >= 0


async def test_empty_or_nonfinite_evidence_degrades_to_active() -> None:
    query = ProbeQuery(
        probe_id="vm_traffic_last_5m",
        target_ref="resource-1",
        deadline_seconds=1,
    )

    assert (await _probe([]).measure(query)).degraded is True
    invalid = await _probe([float("nan")]).measure(query)
    assert invalid.verdict is ProbeVerdict.ACTIVE
    assert invalid.degraded is True


def test_shipped_azure_monitor_manifests_compile() -> None:
    manifests = load_probe_catalog(_ROOT / "rule-catalog" / "probes")
    definitions = azure_monitor_probe_definitions(manifests)

    assert {definition.probe_id for definition in definitions} == {
        "lb_backend_health",
        "storage_access_log",
        "vm_traffic_last_5m",
    }
    assert {definition.timeout_seconds for definition in definitions} == {5}


async def test_probe_enforces_manifest_timeout_before_caller_maximum() -> None:
    class SlowMetricProvider:
        async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
            del query
            await asyncio.sleep(0.05)
            yield MetricPoint(
                metric_name="Network In Total",
                at=_NOW,
                value=1.0,
            )

    definition = _definition()
    probe = AzureMonitorBlastProbe(
        metric_provider=SlowMetricProvider(),
        definitions=(
            AzureMonitorProbeDefinition(
                probe_id=definition.probe_id,
                metric_name=definition.metric_name,
                aggregation=definition.aggregation,
                window_minutes=definition.window_minutes,
                timeout_seconds=0.01,
                result_field=definition.result_field,
                quiet_below=definition.quiet_below,
                active_below=definition.active_below,
            ),
        ),
        clock=lambda: _NOW,
    )

    with pytest.raises(BlastProbeTimeoutError):
        await probe.measure(
            ProbeQuery(
                probe_id=definition.probe_id,
                target_ref="resource-1",
                deadline_seconds=1,
            )
        )


def test_invalid_or_duplicate_definitions_fail_closed() -> None:
    with pytest.raises(BlastProbeConfigError, match="unique"):
        AzureMonitorBlastProbe(
            metric_provider=StaticMetricProvider(()),
            definitions=(_definition(), _definition()),
        )
