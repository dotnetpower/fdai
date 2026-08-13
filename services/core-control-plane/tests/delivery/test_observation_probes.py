"""Focused source-catalog and provider-probe tests."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.delivery.observation_campaign import ObservationCoverage, ObservationSourceSpec
from fdai.delivery.observation_probes import (
    InventoryDeltaObservationProbe,
    LogQueryObservationProbe,
    MetricObservationProbe,
)
from fdai.delivery.observation_source_catalog import load_observation_source_catalog
from fdai.shared.providers.inventory import InventoryBatch, ResourceRecord
from fdai.shared.providers.log_query import LogRecord, StaticLogQueryProvider
from fdai.shared.providers.metric import MetricPoint, StaticMetricProvider
from fdai_service_contracts import ObservationDomain

_ROOT = Path(__file__).resolve().parents[4]


def _spec(domain: ObservationDomain, *, max_results: int = 10) -> ObservationSourceSpec:
    owner = "Huginn" if domain is ObservationDomain.ACTIVITY_LOG else "Heimdall"
    return ObservationSourceSpec(
        source_id=domain.value,
        domain=domain,
        owner_agent=owner,  # type: ignore[arg-type]
        interval_seconds=60,
        lookback_seconds=300,
        timeout_seconds=1,
        max_targets=4,
        max_results=max_results,
        max_output_bytes=1024,
    )


def test_catalog_covers_every_domain_with_bounded_parallelism() -> None:
    catalog = load_observation_source_catalog(_ROOT / "config/observation-sources.yaml")

    assert catalog.max_concurrency == 4
    assert {source.domain for source in catalog.sources} == set(ObservationDomain)
    assert catalog.digest.startswith("sha256:")


def test_catalog_rejects_unknown_fields_and_uses_semantic_digest(tmp_path: Path) -> None:
    original = (_ROOT / "config/observation-sources.yaml").read_text(encoding="utf-8")
    with_comment = tmp_path / "with-comment.yaml"
    with_comment.write_text(f"# formatting only\n{original}", encoding="utf-8")

    original_catalog = load_observation_source_catalog(_ROOT / "config/observation-sources.yaml")
    commented_catalog = load_observation_source_catalog(with_comment)

    assert commented_catalog.digest == original_catalog.digest

    invalid = tmp_path / "invalid.yaml"
    invalid.write_text(
        re.sub(
            r"(  - id: inventory\n)",
            r"\1    executable_query: resources\n",
            original,
            count=1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported fields"):
        load_observation_source_catalog(invalid)


async def test_inventory_delta_probe_counts_records_and_advances_cursor() -> None:
    class Inventory:
        async def delta(self, cursor: str):
            assert cursor == "cursor-1"
            yield InventoryBatch(
                resources=(ResourceRecord(resource_id="r1", type="compute.vm"),),
                cursor="cursor-2",
                final=True,
            )

    result = await InventoryDeltaObservationProbe(Inventory()).collect(
        _spec(ObservationDomain.ACTIVITY_LOG),
        cursor="cursor-1",
    )

    assert result.coverage is ObservationCoverage.READY
    assert result.evidence_count == 1
    assert result.cursor == "cursor-2"


async def test_log_probe_enforces_output_budget_without_retaining_bodies() -> None:
    now = datetime(2026, 8, 14, tzinfo=UTC)
    provider = StaticLogQueryProvider(
        (
            LogRecord(at=now, body="x" * 700, severity="info"),
            LogRecord(at=now, body="y" * 700, severity="warn"),
        )
    )
    with pytest.raises(ValueError, match="bounded non-empty"):
        LogQueryObservationProbe(provider, expression="", clock=lambda: now)

    bounded = LogQueryObservationProbe(provider, expression="x", clock=lambda: now)
    result = await bounded.collect(_spec(ObservationDomain.LOGS), cursor=None)
    assert result.coverage is ObservationCoverage.READY
    assert result.evidence_count == 1


async def test_metric_probe_reports_limit_as_partial() -> None:
    now = datetime(2026, 8, 14, tzinfo=UTC)
    provider = StaticMetricProvider(
        tuple(MetricPoint(metric_name="cpu", at=now, value=float(index)) for index in range(3))
    )
    result = await MetricObservationProbe(
        provider,
        metric_names=("cpu",),
        clock=lambda: now,
    ).collect(
        _spec(ObservationDomain.METRICS, max_results=2),
        cursor=None,
    )

    assert result.coverage is ObservationCoverage.PARTIAL
    assert result.evidence_count == 2
    assert result.reason_codes == ("result_limit",)


async def test_metric_probe_enforces_serialized_byte_budget() -> None:
    now = datetime(2026, 8, 14, tzinfo=UTC)
    provider = StaticMetricProvider(
        (
            MetricPoint(
                metric_name="cpu",
                at=now,
                value=1.0,
                labels={"dimension": "x" * 2_000},
            ),
        )
    )
    result = await MetricObservationProbe(
        provider,
        metric_names=("cpu",),
        clock=lambda: now,
    ).collect(
        _spec(ObservationDomain.METRICS),
        cursor=None,
    )

    assert result.coverage is ObservationCoverage.PARTIAL
    assert result.evidence_count == 1
    assert result.reason_codes == ("byte_limit",)
