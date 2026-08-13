"""Focused observation campaign lifecycle tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fdai.delivery.observation_campaign import (
    ObservationCampaignRunner,
    ObservationCoverage,
    ObservationProbeResult,
    ObservationSourceSpec,
    ObservationThrottledError,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts import ObservationDomain


class RecordingPublisher:
    def __init__(self) -> None:
        self.items = []

    async def publish(self, activity):  # type: ignore[no-untyped-def]
        self.items.append(activity)
        return True


class FailingPublisher:
    async def publish(self, activity):  # type: ignore[no-untyped-def]
        del activity
        raise RuntimeError("broker unavailable")


class Probe:
    def __init__(self, result: ObservationProbeResult | Exception) -> None:
        self.result = result
        self.calls: list[str | None] = []

    async def collect(self, spec, *, cursor):  # type: ignore[no-untyped-def]
        del spec
        self.calls.append(cursor)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _source(
    source_id: str,
    domain: ObservationDomain,
    owner: str,
    *,
    required: bool = True,
) -> ObservationSourceSpec:
    return ObservationSourceSpec(
        source_id=source_id,
        domain=domain,
        owner_agent=owner,  # type: ignore[arg-type]
        interval_seconds=60,
        lookback_seconds=300,
        timeout_seconds=1,
        max_targets=16,
        max_results=100,
        max_output_bytes=64_000,
        required=required,
    )


async def test_runs_all_due_sources_and_publishes_after_terminal_state() -> None:
    store = InMemoryStateStore()
    publisher = RecordingPublisher()
    probes = {
        "activity-log": Probe(
            ObservationProbeResult(
                coverage=ObservationCoverage.READY,
                evidence_count=3,
                cursor="cursor-1",
            )
        ),
        "resource-health": Probe(
            ObservationProbeResult(
                coverage=ObservationCoverage.READY,
                evidence_count=2,
            )
        ),
    }
    runner = ObservationCampaignRunner(
        sources=(
            _source("activity-log", ObservationDomain.ACTIVITY_LOG, "Huginn"),
            _source("resource-health", ObservationDomain.RESOURCE_HEALTH, "Heimdall"),
        ),
        probes=probes,
        store=store,
        publisher=publisher,
    )

    summary = await runner.run("campaign-1")

    assert summary.status == "completed"
    assert [item.status.value for item in publisher.items].count("started") == 2
    assert [item.status.value for item in publisher.items].count("completed") == 2
    saved = await store.read_state("observation-campaign:source:activity-log")
    assert saved is not None and saved["cursor"] == "cursor-1"


async def test_isolates_permission_denial_and_reports_partial() -> None:
    publisher = RecordingPublisher()
    runner = ObservationCampaignRunner(
        sources=(
            _source("activity-log", ObservationDomain.ACTIVITY_LOG, "Huginn"),
            _source("resource-health", ObservationDomain.RESOURCE_HEALTH, "Heimdall"),
        ),
        probes={
            "activity-log": Probe(PermissionError("denied")),
            "resource-health": Probe(
                ObservationProbeResult(
                    coverage=ObservationCoverage.READY,
                    evidence_count=1,
                )
            ),
        },
        store=InMemoryStateStore(),
        publisher=publisher,
    )

    summary = await runner.run("campaign-2")

    assert summary.status == "partial"
    assert summary.sources[0].coverage is ObservationCoverage.UNAUTHORIZED
    assert summary.sources[1].coverage is ObservationCoverage.READY
    assert summary.sources[0].reason_codes == ("source_unauthorized",)


async def test_normalizes_throttling_as_expected_partial_coverage() -> None:
    runner = ObservationCampaignRunner(
        sources=(_source("activity-log", ObservationDomain.ACTIVITY_LOG, "Huginn"),),
        probes={"activity-log": Probe(ObservationThrottledError("throttled"))},
        store=InMemoryStateStore(),
        publisher=RecordingPublisher(),
    )

    summary = await runner.run("campaign-throttled")

    assert summary.status == "partial"
    assert summary.sources[0].status.value == "degraded"
    assert summary.sources[0].coverage is ObservationCoverage.PARTIAL
    assert summary.sources[0].reason_codes == ("source_throttled",)


async def test_rejects_probe_count_above_registered_result_limit() -> None:
    runner = ObservationCampaignRunner(
        sources=(_source("logs", ObservationDomain.LOGS, "Heimdall"),),
        probes={
            "logs": Probe(
                ObservationProbeResult(
                    coverage=ObservationCoverage.READY,
                    evidence_count=101,
                )
            )
        },
        store=InMemoryStateStore(),
        publisher=RecordingPublisher(),
    )

    summary = await runner.run("campaign-contract")

    assert summary.status == "partial"
    assert summary.sources[0].status.value == "failed"
    assert summary.sources[0].evidence_count == 0
    assert summary.sources[0].reason_codes == ("provider_contract_violation",)


async def test_publisher_failure_does_not_block_durable_source_collection() -> None:
    store = InMemoryStateStore()
    probe = Probe(ObservationProbeResult(coverage=ObservationCoverage.READY))
    runner = ObservationCampaignRunner(
        sources=(_source("logs", ObservationDomain.LOGS, "Heimdall"),),
        probes={"logs": probe},
        store=store,
        publisher=FailingPublisher(),
    )

    summary = await runner.run("campaign-publisher-failure")

    assert summary.status == "completed"
    assert probe.calls == [None]
    saved = await store.read_state("observation-campaign:source:logs")
    assert saved is not None and saved["status"] == "completed"


async def test_missing_optional_probe_is_visible_without_failing_campaign() -> None:
    publisher = RecordingPublisher()
    runner = ObservationCampaignRunner(
        sources=(
            _source(
                "guest-logs",
                ObservationDomain.GUEST_LOGS,
                "Heimdall",
                required=False,
            ),
        ),
        probes={},
        store=InMemoryStateStore(),
        publisher=publisher,
    )

    summary = await runner.run("campaign-3")

    assert summary.status == "completed"
    assert summary.sources[0].coverage is ObservationCoverage.UNCONFIGURED
    assert publisher.items[-1].reason_codes == ("source_unconfigured",)


async def test_same_campaign_replays_terminal_without_provider_or_activity() -> None:
    probe = Probe(ObservationProbeResult(coverage=ObservationCoverage.READY))
    publisher = RecordingPublisher()
    runner = ObservationCampaignRunner(
        sources=(_source("logs", ObservationDomain.LOGS, "Heimdall"),),
        probes={"logs": probe},
        store=InMemoryStateStore(),
        publisher=publisher,
    )

    first = await runner.run("campaign-4")
    second = await runner.run("campaign-4")

    assert first == second
    assert probe.calls == [None]
    assert len(publisher.items) == 2


async def test_same_campaign_recollects_malformed_terminal_state() -> None:
    store = InMemoryStateStore()
    await store.write_state(
        "observation-campaign:source:logs",
        {
            "revision": 1,
            "source_id": "logs",
            "domain": "logs",
            "campaign_id": "campaign-malformed",
            "status": "completed",
            "coverage": "ready",
            "freshness": "fresh",
            "evidence_count": 1,
            "duration_ms": 2,
            "reason_codes": [],
        },
    )
    probe = Probe(ObservationProbeResult(coverage=ObservationCoverage.READY))
    runner = ObservationCampaignRunner(
        sources=(_source("logs", ObservationDomain.LOGS, "Heimdall"),),
        probes={"logs": probe},
        store=store,
        publisher=RecordingPublisher(),
    )

    summary = await runner.run("campaign-malformed")

    assert summary.status == "completed"
    assert probe.calls == [None]
    saved = await store.read_state("observation-campaign:source:logs")
    assert saved is not None and saved["revision"] == 3


async def test_not_due_source_skips_without_activity() -> None:
    clock = SimpleNamespace(now=datetime(2026, 8, 14, tzinfo=UTC))
    store = InMemoryStateStore()
    await store.write_state(
        "observation-campaign:source:logs",
        {
            "campaign_id": "earlier",
            "status": "completed",
            "coverage": "ready",
            "freshness": "fresh",
            "completed_at": clock.now.isoformat(),
        },
    )
    publisher = RecordingPublisher()
    runner = ObservationCampaignRunner(
        sources=(_source("logs", ObservationDomain.LOGS, "Heimdall"),),
        probes={"logs": Probe(ObservationProbeResult(coverage=ObservationCoverage.READY))},
        store=store,
        publisher=publisher,
        clock=lambda: clock.now + timedelta(seconds=30),
    )

    summary = await runner.run("campaign-5")

    assert summary.status == "completed"
    assert summary.sources[0].skipped
    assert publisher.items == []


async def test_not_due_source_preserves_last_degraded_evidence_state() -> None:
    clock = SimpleNamespace(now=datetime(2026, 8, 14, tzinfo=UTC))
    store = InMemoryStateStore()
    await store.write_state(
        "observation-campaign:source:logs",
        {
            "campaign_id": "earlier",
            "status": "degraded",
            "coverage": "stale",
            "freshness": "stale",
            "completed_at": clock.now.isoformat(),
            "evidence_count": 7,
            "duration_ms": 20,
            "reason_codes": ["source_stale"],
        },
    )
    probe = Probe(ObservationProbeResult(coverage=ObservationCoverage.READY))
    runner = ObservationCampaignRunner(
        sources=(_source("logs", ObservationDomain.LOGS, "Heimdall"),),
        probes={"logs": probe},
        store=store,
        publisher=RecordingPublisher(),
        clock=lambda: clock.now + timedelta(seconds=30),
    )

    summary = await runner.run("campaign-not-due")

    assert summary.status == "partial"
    assert summary.sources[0].skipped
    assert summary.sources[0].coverage is ObservationCoverage.STALE
    assert summary.sources[0].freshness.value == "stale"
    assert summary.sources[0].evidence_count == 7
    assert probe.calls == []


async def test_cursor_advances_only_after_terminal_state_write() -> None:
    store = InMemoryStateStore()
    await store.write_state(
        "observation-campaign:source:activity-log",
        {
            "campaign_id": "earlier",
            "status": "completed",
            "coverage": "ready",
            "freshness": "fresh",
            "completed_at": "2026-08-13T00:00:00+00:00",
            "cursor": "cursor-1",
        },
    )
    probe = Probe(
        ObservationProbeResult(
            coverage=ObservationCoverage.READY,
            evidence_count=1,
            cursor="cursor-2",
        )
    )
    runner = ObservationCampaignRunner(
        sources=(_source("activity-log", ObservationDomain.ACTIVITY_LOG, "Huginn"),),
        probes={"activity-log": probe},
        store=store,
        publisher=RecordingPublisher(),
        clock=lambda: datetime(2026, 8, 14, tzinfo=UTC),
    )

    await runner.run("campaign-6")

    assert probe.calls == ["cursor-1"]
    saved = await store.read_state("observation-campaign:source:activity-log")
    assert saved is not None and saved["cursor"] == "cursor-2"


async def test_concurrency_is_capped_at_four() -> None:
    active = 0
    maximum = 0

    class ConcurrentProbe:
        async def collect(self, spec, *, cursor):  # type: ignore[no-untyped-def]
            nonlocal active, maximum
            del spec, cursor
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0)
            active -= 1
            return ObservationProbeResult(coverage=ObservationCoverage.READY)

    sources = tuple(
        _source(f"logs-{index}", ObservationDomain.LOGS, "Heimdall") for index in range(6)
    )
    runner = ObservationCampaignRunner(
        sources=sources,
        probes={source.source_id: ConcurrentProbe() for source in sources},
        store=InMemoryStateStore(),
        publisher=RecordingPublisher(),
    )

    await runner.run("campaign-7")

    assert maximum == 4


async def test_atomic_claim_prevents_duplicate_probe_across_runners() -> None:
    store = InMemoryStateStore()
    publisher = RecordingPublisher()
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingProbe:
        def __init__(self) -> None:
            self.calls: list[str | None] = []

        async def collect(self, spec, *, cursor):  # type: ignore[no-untyped-def]
            del spec
            self.calls.append(cursor)
            entered.set()
            await release.wait()
            return ObservationProbeResult(coverage=ObservationCoverage.READY)

    probe = BlockingProbe()
    source = _source("activity-log", ObservationDomain.ACTIVITY_LOG, "Huginn")
    runners = tuple(
        ObservationCampaignRunner(
            sources=(source,),
            probes={source.source_id: probe},
            store=store,
            publisher=publisher,
        )
        for _ in range(2)
    )

    first = asyncio.create_task(runners[0].run("campaign-concurrent"))
    await entered.wait()
    second = await runners[1].run("campaign-concurrent")
    release.set()
    first_summary = await first

    assert probe.calls == [None]
    assert first_summary.status == "completed"
    assert second.status == "partial"
    assert second.sources[0].reason_codes == ("source_in_progress",)
    saved = await store.read_state("observation-campaign:source:activity-log")
    assert saved is not None and saved["revision"] == 2


async def test_expired_claim_is_recovered() -> None:
    store = InMemoryStateStore()
    await store.write_state(
        "observation-campaign:source:logs",
        {
            "revision": 1,
            "campaign_id": "campaign-crashed",
            "status": "started",
            "claim_expires_at": "2026-08-13T00:00:00+00:00",
        },
    )
    probe = Probe(ObservationProbeResult(coverage=ObservationCoverage.READY))
    runner = ObservationCampaignRunner(
        sources=(_source("logs", ObservationDomain.LOGS, "Heimdall"),),
        probes={"logs": probe},
        store=store,
        publisher=RecordingPublisher(),
        clock=lambda: datetime(2026, 8, 14, tzinfo=UTC),
    )

    summary = await runner.run("campaign-recovery")

    assert summary.status == "completed"
    assert probe.calls == [None]
    saved = await store.read_state("observation-campaign:source:logs")
    assert saved is not None and saved["revision"] == 3
