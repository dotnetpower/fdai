"""Analyzer tick: canonical Event publication, idempotency, and retry behaviour."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fdai.core.investigation import (
    AnalyzerFinding,
    InvestigationCoordinator,
    InvestigationRequest,
)
from fdai.core.investigation.contract import InvestigationReport
from fdai.delivery.analyzer_tick import (
    ANALYZER_EVENT_SOURCE,
    ANALYZER_EVENT_TOPIC,
    AnalyzerPublicationClaim,
    AnalyzerTarget,
    AnalyzerTickRunner,
    analyzer_idempotency_key,
)
from fdai.delivery.analyzer_tick_cli import (
    DEFAULT_MAX_DISCOVERED,
    INVENTORY_DSN_ENV,
    build_inventory_projection,
    parse_max_discovered,
    parse_targets,
    parse_trace_topologies,
    parse_window_seconds,
)
from fdai.delivery.persistence.postgres_analyzer_publication import (
    PostgresAnalyzerPublicationLedger,
)
from fdai.shared.contracts.models import Mode, Severity
from fdai.shared.providers.event_bus import (
    EventPublishNotAttemptedError,
    PublishReceipt,
)

from tests.delivery.publication_store import ConditionalStore

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def _finding(*, resource_ref: str = "res-1", signal: str = "cpu_saturation") -> AnalyzerFinding:
    return AnalyzerFinding(
        resource_ref=resource_ref,
        resource_kind="aks",
        signal=signal,
        observation="Node CPU stayed above its bound.",
        severity=Severity.HIGH,
        occurred_at=NOW,
        evidence_refs=("node_cpu_usage",),
        remediation_ref="ops.scale-out",
    )


class StubCoordinator(InvestigationCoordinator):
    def __init__(
        self,
        *,
        findings: tuple[AnalyzerFinding, ...] = (),
        analyzer_errors: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__(analyzers=())
        self._findings = findings
        self._analyzer_errors = analyzer_errors
        self.requests: list[InvestigationRequest] = []

    async def investigate(self, request: InvestigationRequest) -> InvestigationReport:
        self.requests.append(request)
        report = await super().investigate(request)
        return replace(
            report,
            findings=self._findings,
            analyzer_errors=self._analyzer_errors or report.analyzer_errors,
        )


class RecordingBus:
    def __init__(self, *, fail_on: str | None = None) -> None:
        self.published: list[tuple[str, str, dict[str, object]]] = []
        self._fail_on = fail_on

    async def publish(self, topic: str, key: str, payload: dict[str, object]) -> PublishReceipt:
        if self._fail_on is not None and key == self._fail_on:
            raise RuntimeError("broker unavailable")
        self.published.append((topic, key, payload))
        return PublishReceipt(topic=topic, partition=0, offset=len(self.published) - 1)


class FailingLedger:
    """Wrap the durable ledger and fail one exact transition."""

    def __init__(
        self,
        inner: PostgresAnalyzerPublicationLedger,
        *,
        fail_complete: bool = False,
        fail_claim_on: str | None = None,
        fail_sending: bool = False,
    ) -> None:
        self._inner = inner
        self._fail_complete = fail_complete
        self._fail_claim_on = fail_claim_on
        self._fail_sending = fail_sending

    async def claim(self, idempotency_key: str) -> AnalyzerPublicationClaim:
        if self._fail_claim_on is not None and self._fail_claim_on in idempotency_key:
            raise RuntimeError("claim store unavailable")
        return await self._inner.claim(idempotency_key)

    async def mark_sending(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
    ) -> AnalyzerPublicationClaim:
        if self._fail_sending:
            raise RuntimeError("store unavailable")
        return await self._inner.mark_sending(idempotency_key, claim)

    async def mark_uncertain(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
        *,
        reason: str,
    ) -> AnalyzerPublicationClaim:
        return await self._inner.mark_uncertain(idempotency_key, claim, reason=reason)

    async def complete(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
        receipt: PublishReceipt,
    ) -> None:
        if self._fail_complete:
            raise RuntimeError("store unavailable")
        await self._inner.complete(idempotency_key, claim, receipt)

    async def release(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
        *,
        provably_unsent: bool = False,
    ) -> None:
        await self._inner.release(idempotency_key, claim, provably_unsent=provably_unsent)


class RecordingReconciler:
    """Return one pre-decided independent observation per key."""

    def __init__(
        self,
        *,
        receipt: PublishReceipt | None = None,
        undecidable: bool = False,
    ) -> None:
        self.calls: list[str] = []
        self._receipt = receipt
        self._undecidable = undecidable

    async def reconcile(
        self,
        *,
        event_id: UUID,
        idempotency_key: str,
        topic: str,
    ) -> PublishReceipt | None:
        self.calls.append(idempotency_key)
        if self._undecidable:
            raise RuntimeError("broker history unavailable")
        return self._receipt


def _ledger(store: ConditionalStore | None = None, **kwargs: object) -> FailingLedger:
    inner = PostgresAnalyzerPublicationLedger(store=store or ConditionalStore())
    return FailingLedger(inner, **kwargs)  # type: ignore[arg-type]


def _states(store: ConditionalStore) -> list[str]:
    return [str(record["state"]) for record in store.values.values()]


def _runner(
    coordinator: InvestigationCoordinator,
    bus: RecordingBus,
    *,
    ledger: FailingLedger | None = None,
    reconciler: RecordingReconciler | None = None,
    clock: Callable[[], datetime] = lambda: NOW,
) -> AnalyzerTickRunner:
    return AnalyzerTickRunner(
        coordinator=coordinator,
        event_bus=bus,  # type: ignore[arg-type]
        publication_ledger=ledger or _ledger(),  # type: ignore[arg-type]
        publication_reconciler=reconciler,  # type: ignore[arg-type]
        window_seconds=300,
        clock=clock,
    )


# ---------------------------------------------------------------------------
# Canonical publication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_each_finding_publishes_one_canonical_event() -> None:
    bus = RecordingBus()
    runner = _runner(StubCoordinator(findings=(_finding(),)), bus)

    report = await runner.run_once((AnalyzerTarget(resource_ref="res-1", resource_kind="aks"),))

    assert report.published == 1
    topic, key, payload = bus.published[0]
    assert topic == ANALYZER_EVENT_TOPIC
    assert key == "res-1"
    assert payload["source"] == ANALYZER_EVENT_SOURCE
    assert payload["event_type"] == "analyzer.cpu_saturation.observed"
    assert payload["mode"] == Mode.SHADOW.value
    assert payload["payload"]["remediation_ref"] == "ops.scale-out"


@pytest.mark.asyncio
async def test_no_targets_publishes_nothing_and_succeeds() -> None:
    bus = RecordingBus()
    report = await _runner(StubCoordinator(), bus).run_once(())

    assert report.to_dict()["targets"] == 0
    assert not report.failed
    assert bus.published == []


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_idempotency_key_is_stable_inside_one_window() -> None:
    finding = _finding()
    first = analyzer_idempotency_key(finding, at=NOW, window_seconds=300)
    later = analyzer_idempotency_key(
        finding, at=NOW.replace(minute=4, second=59), window_seconds=300
    )
    next_window = analyzer_idempotency_key(finding, at=NOW.replace(minute=5), window_seconds=300)

    assert first == later
    assert first != next_window


@pytest.mark.asyncio
async def test_a_retried_tick_suppresses_the_same_key() -> None:
    bus = RecordingBus()
    ledger = _ledger()
    runner = _runner(StubCoordinator(findings=(_finding(),)), bus, ledger=ledger)
    targets = (AnalyzerTarget(resource_ref="res-1", resource_kind="aks"),)

    first = await runner.run_once(targets)
    duplicate = await runner.run_once(targets)

    keys = {payload["idempotency_key"] for _, _, payload in bus.published}
    assert len(bus.published) == 1
    assert len(keys) == 1
    assert first.published == 1
    assert first.duplicates_suppressed == 0
    assert duplicate.published == 0
    assert duplicate.duplicates_suppressed == 1
    assert duplicate.receipts[0].publication.value == "duplicate_suppressed"


@pytest.mark.asyncio
async def test_receipt_latency_uses_post_analysis_broker_ack_time() -> None:
    times = iter(
        (
            NOW,
            NOW.replace(second=20),
            NOW.replace(second=21),
        )
    )
    bus = RecordingBus()

    report = await _runner(
        StubCoordinator(findings=(_finding(),)),
        bus,
        clock=lambda: next(times),
    ).run_once((AnalyzerTarget(resource_ref="res-1", resource_kind="aks"),))

    assert bus.published[0][2]["ingested_at"] == "2026-08-15T12:00:20Z"
    assert report.receipts[0].detection_latency_seconds == 21.0


@pytest.mark.asyncio
async def test_active_publication_claim_fails_tick_without_publishing() -> None:
    bus = RecordingBus()
    store = ConditionalStore()
    ledger = _ledger(store)
    key = analyzer_idempotency_key(_finding(), at=NOW, window_seconds=300)
    await ledger.claim(key)

    report = await _runner(
        StubCoordinator(findings=(_finding(),)),
        bus,
        ledger=_ledger(store),
    ).run_once((AnalyzerTarget(resource_ref="res-1", resource_kind="aks"),))

    assert report.failed
    assert report.duplicates_suppressed == 0
    assert report.publish_errors == ((key, "RuntimeError:publication_claim_in_progress"),)
    assert bus.published == []


@pytest.mark.asyncio
async def test_unreadable_publication_claim_fails_closed_for_that_finding_only() -> None:
    bus = RecordingBus()
    ledger = _ledger(fail_claim_on="res-1")
    coordinator = StubCoordinator(
        findings=(_finding(resource_ref="res-1"), _finding(resource_ref="res-2"))
    )

    report = await _runner(coordinator, bus, ledger=ledger).run_once(
        (
            AnalyzerTarget(resource_ref="res-1", resource_kind="aks"),
            AnalyzerTarget(resource_ref="res-2", resource_kind="aks"),
        )
    )

    assert report.failed
    assert report.published == 1
    assert report.duplicates_suppressed == 0
    assert [key for _, key, _ in bus.published] == ["res-2"]
    blocked = next(item for item in report.receipts if "res-1" in item.idempotency_key)
    assert blocked.publication.value == "failed"
    assert report.publish_errors[0][1] == ("publication_claim=RuntimeError:claim store unavailable")


@pytest.mark.asyncio
async def test_broker_success_with_unrecorded_receipt_is_reported_without_release() -> None:
    bus = RecordingBus()
    ledger = _ledger(fail_complete=True)

    report = await _runner(
        StubCoordinator(findings=(_finding(),)),
        bus,
        ledger=ledger,
    ).run_once((AnalyzerTarget(resource_ref="res-1", resource_kind="aks"),))

    assert report.failed
    assert report.published == 1
    assert len(bus.published) == 1
    assert report.receipts[0].publication.value == "published_receipt_unrecorded"
    assert report.publish_errors[0][1] == "publication_receipt=RuntimeError:store unavailable"


@pytest.mark.asyncio
async def test_uncertain_publication_is_not_republished_by_the_next_tick() -> None:
    bus = RecordingBus()
    ledger = _ledger(fail_complete=True)
    runner = _runner(StubCoordinator(findings=(_finding(),)), bus, ledger=ledger)
    targets = (AnalyzerTarget(resource_ref="res-1", resource_kind="aks"),)

    first = await runner.run_once(targets)
    second = await runner.run_once(targets)

    assert first.receipts[0].publication.value == "published_receipt_unrecorded"
    assert second.failed
    assert second.published == 0
    assert second.duplicates_suppressed == 0
    assert len(bus.published) == 1
    assert second.publish_errors[0][1] == "RuntimeError:publication_claim_in_progress"


@pytest.mark.asyncio
async def test_a_provably_unsent_record_is_released_and_retried_next_tick() -> None:
    class _FlakyBus(RecordingBus):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        async def publish(self, topic: str, key: str, payload: dict[str, object]) -> PublishReceipt:
            self.attempts += 1
            if self.attempts == 1:
                raise EventPublishNotAttemptedError("producer unavailable")
            return await super().publish(topic, key, payload)

    bus = _FlakyBus()
    store = ConditionalStore()
    runner = _runner(StubCoordinator(findings=(_finding(),)), bus, ledger=_ledger(store))
    targets = (AnalyzerTarget(resource_ref="res-1", resource_kind="aks"),)

    first = await runner.run_once(targets)
    retry = await runner.run_once(targets)

    assert first.failed
    assert first.uncertain == 0
    assert first.receipts[0].publication.value == "failed"
    assert retry.published == 1
    assert not retry.failed
    assert len(bus.published) == 1
    assert _states(store) == ["completed"]


@pytest.mark.asyncio
async def test_an_ambiguous_broker_error_preserves_the_claim_and_blocks_retry() -> None:
    bus = RecordingBus(fail_on="res-1")
    store = ConditionalStore()
    runner = _runner(StubCoordinator(findings=(_finding(),)), bus, ledger=_ledger(store))
    targets = (AnalyzerTarget(resource_ref="res-1", resource_kind="aks"),)

    first = await runner.run_once(targets)
    second = await runner.run_once(targets)

    assert first.failed
    assert first.published == 0
    assert first.uncertain == 1
    assert first.receipts[0].publication.value == "publish_uncertain"
    assert first.publish_errors[0][1] == "publish_uncertain=RuntimeError:broker unavailable"
    assert _states(store) == ["uncertain"]
    assert second.published == 0
    assert second.uncertain == 1
    assert second.receipts[0].publication.value == "awaiting_reconciliation"
    assert second.publish_errors[0][1] == "RuntimeError:publication_reconciler_unbound"
    assert bus.published == []


@pytest.mark.asyncio
async def test_reconciliation_finding_a_broker_receipt_suppresses_the_duplicate() -> None:
    bus = RecordingBus(fail_on="res-1")
    store = ConditionalStore()
    targets = (AnalyzerTarget(resource_ref="res-1", resource_kind="aks"),)
    await _runner(StubCoordinator(findings=(_finding(),)), bus, ledger=_ledger(store)).run_once(
        targets
    )
    reconciler = RecordingReconciler(
        receipt=PublishReceipt(topic=ANALYZER_EVENT_TOPIC, partition=0, offset=4)
    )

    resolved = await _runner(
        StubCoordinator(findings=(_finding(),)),
        RecordingBus(),
        ledger=_ledger(store),
        reconciler=reconciler,
    ).run_once(targets)

    assert resolved.published == 0
    assert resolved.duplicates_suppressed == 1
    assert not resolved.failed
    assert resolved.receipts[0].publication.value == "reconciled_duplicate"
    assert len(reconciler.calls) == 1
    assert _states(store) == ["completed"]


@pytest.mark.asyncio
async def test_reconciliation_proving_no_send_allows_exactly_one_retry() -> None:
    store = ConditionalStore()
    targets = (AnalyzerTarget(resource_ref="res-1", resource_kind="aks"),)
    await _runner(
        StubCoordinator(findings=(_finding(),)),
        RecordingBus(fail_on="res-1"),
        ledger=_ledger(store),
    ).run_once(targets)
    bus = RecordingBus()

    retried = await _runner(
        StubCoordinator(findings=(_finding(),)),
        bus,
        ledger=_ledger(store),
        reconciler=RecordingReconciler(),
    ).run_once(targets)

    assert retried.published == 1
    assert not retried.failed
    assert len(bus.published) == 1
    assert _states(store) == ["completed"]


@pytest.mark.asyncio
async def test_an_undecidable_reconciliation_never_republishes() -> None:
    store = ConditionalStore()
    targets = (AnalyzerTarget(resource_ref="res-1", resource_kind="aks"),)
    await _runner(
        StubCoordinator(findings=(_finding(),)),
        RecordingBus(fail_on="res-1"),
        ledger=_ledger(store),
    ).run_once(targets)
    bus = RecordingBus()

    blocked = await _runner(
        StubCoordinator(findings=(_finding(),)),
        bus,
        ledger=_ledger(store),
        reconciler=RecordingReconciler(undecidable=True),
    ).run_once(targets)

    assert blocked.failed
    assert blocked.published == 0
    assert blocked.uncertain == 1
    assert blocked.receipts[0].publication.value == "awaiting_reconciliation"
    assert blocked.publish_errors[0][1].startswith("publication_reconcile=RuntimeError:")
    assert bus.published == []
    assert _states(store) == ["uncertain"]


@pytest.mark.asyncio
async def test_a_crash_after_an_acknowledged_publish_never_republishes_on_lease_expiry() -> None:
    bus = RecordingBus()
    store = ConditionalStore()

    acknowledged = await _runner(
        StubCoordinator(findings=(_finding(),)),
        bus,
        ledger=_ledger(store, fail_complete=True),
    ).run_once((AnalyzerTarget(resource_ref="res-1", resource_kind="aks"),))
    assert acknowledged.receipts[0].publication.value == "published_receipt_unrecorded"
    key = next(iter(store.values))
    store.values[key]["claimed_at"] = "2026-08-15T00:00:00+00:00"

    expired = AnalyzerTickRunner(
        coordinator=StubCoordinator(findings=(_finding(),)),
        event_bus=bus,  # type: ignore[arg-type]
        publication_ledger=PostgresAnalyzerPublicationLedger(store=store, lease_seconds=1),
        window_seconds=300,
        clock=lambda: NOW,
    )
    report = await expired.run_once((AnalyzerTarget(resource_ref="res-1", resource_kind="aks"),))

    assert len(bus.published) == 1
    assert report.published == 0
    assert report.uncertain == 1
    assert report.receipts[0].publication.value == "awaiting_reconciliation"
    assert _states(store) == ["uncertain"]


@pytest.mark.asyncio
async def test_an_unrecorded_send_intent_never_reaches_the_broker() -> None:
    bus = RecordingBus()
    store = ConditionalStore()

    report = await _runner(
        StubCoordinator(findings=(_finding(),)),
        bus,
        ledger=_ledger(store, fail_sending=True),
    ).run_once((AnalyzerTarget(resource_ref="res-1", resource_kind="aks"),))

    assert report.failed
    assert bus.published == []
    assert report.publish_errors[0][1] == "publication_intent=RuntimeError:store unavailable"
    assert store.values == {}


# ---------------------------------------------------------------------------
# Retry and error reporting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_failure_is_reported_and_does_not_stop_the_pass() -> None:
    bus = RecordingBus(fail_on="res-1")
    store = ConditionalStore()
    ledger = _ledger(store)
    coordinator = StubCoordinator(
        findings=(_finding(resource_ref="res-1"), _finding(resource_ref="res-2"))
    )

    report = await _runner(coordinator, bus, ledger=ledger).run_once(
        (
            AnalyzerTarget(resource_ref="res-1", resource_kind="aks"),
            AnalyzerTarget(resource_ref="res-2", resource_kind="aks"),
        )
    )

    assert report.published == 1
    assert report.failed
    assert report.uncertain == 1
    assert len(report.publish_errors) == 1
    assert report.publish_errors[0][1].startswith("publish_uncertain=RuntimeError:")
    assert sorted(_states(store)) == ["completed", "uncertain"]


@pytest.mark.asyncio
async def test_unsupported_kinds_are_separated_from_analyzer_errors() -> None:
    coordinator = StubCoordinator(
        analyzer_errors=(("res-1", "no_analyzer_for_kind:unknown"), ("res-2", "timeout"))
    )

    report = await _runner(coordinator, RecordingBus()).run_once(
        (
            AnalyzerTarget(resource_ref="res-1", resource_kind="unknown"),
            AnalyzerTarget(resource_ref="res-2", resource_kind="aks"),
        )
    )

    assert report.unsupported_targets == ("res-1",)
    assert report.analyzer_errors == (("res-2", "timeout"),)
    assert not report.failed


@pytest.mark.asyncio
async def test_a_naive_finding_timestamp_fails_closed() -> None:
    bus = RecordingBus()
    naive = replace(_finding(), occurred_at=NOW.replace(tzinfo=None))
    runner = _runner(StubCoordinator(findings=(naive,)), bus)

    with pytest.raises(ValueError, match="naive occurred_at"):
        await runner.run_once((AnalyzerTarget(resource_ref="res-1", resource_kind="aks"),))

    assert bus.published == []


def test_runner_rejects_a_non_positive_window() -> None:
    with pytest.raises(ValueError, match="window_seconds"):
        AnalyzerTickRunner(
            coordinator=StubCoordinator(),
            event_bus=RecordingBus(),  # type: ignore[arg-type]
            publication_ledger=_ledger(),
            window_seconds=0,
        )


# ---------------------------------------------------------------------------
# Configuration parsing
# ---------------------------------------------------------------------------


def test_targets_parse_and_deduplicate() -> None:
    parsed = parse_targets(
        '[{"resource_id": "a", "kind": "aks"}, {"resource_id": "a", "kind": "aks"}]'
    )

    assert parsed == (AnalyzerTarget(resource_ref="a", resource_kind="aks"),)


def test_blank_targets_are_empty_and_malformed_targets_fail_closed() -> None:
    assert parse_targets("  ") == ()
    for raw in ('{"resource_id": "a"}', "[1]", '[{"resource_id": "a"}]', "not-json"):
        with pytest.raises(ValueError):
            parse_targets(raw)


def test_trace_topologies_parse_strict_declarations() -> None:
    parsed = parse_trace_topologies(
        '[{"topology_ref":"agent-request","resource_ref":"trace-topology/agent-request",'
        '"expected_hops":["application","agent","model-endpoint"]}]'
    )

    assert parsed[0].topology_ref == "agent-request"
    assert parsed[0].expected_hops == ("application", "agent", "model-endpoint")


def test_trace_topologies_reject_ambiguous_or_malformed_config() -> None:
    assert parse_trace_topologies(" ") == ()
    invalid = (
        "not-json",
        "{}",
        '[{"topology_ref":"one"}]',
        '[{"topology_ref":"one","resource_ref":"r","expected_hops":["a","b"],"extra":1}]',
        '[{"topology_ref":"one","resource_ref":"r","expected_hops":["a","b"]},'
        '{"topology_ref":"one","resource_ref":"r2","expected_hops":["a","b"]}]',
    )
    for raw in invalid:
        with pytest.raises(ValueError):
            parse_trace_topologies(raw)


def test_window_parsing_fails_closed() -> None:
    assert parse_window_seconds("") == 300
    assert parse_window_seconds(" 60 ") == 60
    for raw in ("0", "-1", "abc"):
        with pytest.raises(ValueError):
            parse_window_seconds(raw)


def test_max_discovered_parsing_fails_closed() -> None:
    assert parse_max_discovered("") == DEFAULT_MAX_DISCOVERED
    assert parse_max_discovered(" 25 ") == 25
    for raw in ("0", "-1", "abc", "1000"):
        with pytest.raises(ValueError):
            parse_max_discovered(raw)


def test_the_projection_stays_unbound_without_a_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(INVENTORY_DSN_ENV, raising=False)

    assert build_inventory_projection() is None
