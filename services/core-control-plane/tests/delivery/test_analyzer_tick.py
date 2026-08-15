"""Analyzer tick: canonical Event publication, idempotency, and retry behaviour."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

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
    AnalyzerTarget,
    AnalyzerTickRunner,
    analyzer_idempotency_key,
)
from fdai.delivery.analyzer_tick_cli import parse_targets, parse_window_seconds
from fdai.shared.contracts.models import Mode, Severity

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

    async def publish(self, topic: str, key: str, payload: dict[str, object]) -> None:
        if self._fail_on is not None and key == self._fail_on:
            raise RuntimeError("broker unavailable")
        self.published.append((topic, key, payload))


def _runner(coordinator: InvestigationCoordinator, bus: RecordingBus) -> AnalyzerTickRunner:
    return AnalyzerTickRunner(
        coordinator=coordinator,
        event_bus=bus,  # type: ignore[arg-type]
        window_seconds=300,
        clock=lambda: NOW,
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
async def test_a_retried_tick_republishes_the_same_key() -> None:
    bus = RecordingBus()
    runner = _runner(StubCoordinator(findings=(_finding(),)), bus)
    targets = (AnalyzerTarget(resource_ref="res-1", resource_kind="aks"),)

    await runner.run_once(targets)
    await runner.run_once(targets)

    keys = {payload["idempotency_key"] for _, _, payload in bus.published}
    assert len(bus.published) == 2
    assert len(keys) == 1


# ---------------------------------------------------------------------------
# Retry and error reporting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_failure_is_reported_and_does_not_stop_the_pass() -> None:
    bus = RecordingBus(fail_on="res-1")
    coordinator = StubCoordinator(
        findings=(_finding(resource_ref="res-1"), _finding(resource_ref="res-2"))
    )

    report = await _runner(coordinator, bus).run_once(
        (
            AnalyzerTarget(resource_ref="res-1", resource_kind="aks"),
            AnalyzerTarget(resource_ref="res-2", resource_kind="aks"),
        )
    )

    assert report.published == 1
    assert report.failed
    assert len(report.publish_errors) == 1
    assert report.publish_errors[0][1].startswith("RuntimeError:")


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


def test_runner_rejects_a_non_positive_window() -> None:
    with pytest.raises(ValueError, match="window_seconds"):
        AnalyzerTickRunner(
            coordinator=StubCoordinator(),
            event_bus=RecordingBus(),  # type: ignore[arg-type]
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


def test_window_parsing_fails_closed() -> None:
    assert parse_window_seconds("") == 300
    assert parse_window_seconds(" 60 ") == 60
    for raw in ("0", "-1", "abc"):
        with pytest.raises(ValueError):
            parse_window_seconds(raw)
