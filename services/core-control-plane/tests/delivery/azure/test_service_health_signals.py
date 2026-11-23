"""Service Health signal detection: pure conversion and the polling job."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.service_health_queries import (
    ServiceHealthCollection,
    ServiceHealthObservation,
)
from fdai.core.report_feed.adapters import signals_from_service_health
from fdai.core.report_feed.models import ReportCategory, ReportSignal, SignalKind
from fdai.delivery.azure.service_health_signals import ServiceHealthSignalJob
from fdai.shared.contracts.models import Severity

_NOW = datetime(2026, 11, 23, 3, 0, tzinfo=UTC)


def _observation(
    event_type: str = "security_advisory",
    *,
    level: str | None = "Warning",
    event: str = "TRK-1",
    impact: str | None = "res-1",
) -> ServiceHealthObservation:
    has_impact = impact is not None
    return ServiceHealthObservation(
        event_id=event,
        event_type=event_type,
        title="Provider supplied title",
        level=level,
        status="active",
        impact_start_at=_NOW - timedelta(hours=2),
        observed_at=_NOW,
        impacted_resource_count=1 if has_impact else 0,
        impacted_resource_ref=f"/subscriptions/s/{impact}" if has_impact else None,
        resource_name=impact,
        resource_type="microsoft.compute/virtualmachines" if has_impact else None,
        resource_group="rg" if has_impact else None,
        region="koreacentral" if has_impact else None,
        impact_status="Impacted" if has_impact else None,
        event_evidence_ref=f"event:{event}",
        impact_evidence_ref=f"impact:{event}:{impact}" if has_impact else None,
    )


def _collection(
    *items: ServiceHealthObservation, complete: bool = True, observed_at: datetime = _NOW
) -> ServiceHealthCollection:
    ordered = tuple(
        sorted(
            (replace(item, observed_at=observed_at) for item in items),
            key=lambda i: (
                i.impact_start_at,
                i.event_id,
                i.resource_name or "",
                i.event_evidence_ref,
                i.impact_evidence_ref or "",
            ),
        )
    )
    return ServiceHealthCollection(
        observations=ordered,
        observed_at=observed_at,
        complete=complete,
        limitation=None if complete else "result_limit",
        attempt_ref="attempt",
    )


def test_security_advisory_becomes_a_security_signal_with_a_severity_floor() -> None:
    (signal,) = signals_from_service_health(_collection(_observation(level="Informational")))

    assert signal.kind is SignalKind.SERVICE_HEALTH
    assert signal.category is ReportCategory.SECURITY
    assert signal.severity is Severity.MEDIUM
    assert signal.metadata["rule_id"] == "service-health.security_advisory"
    assert signal.metadata["execution_authority"] == "false"
    assert "Provider supplied title" not in signal.detail


@pytest.mark.parametrize(
    ("event_type", "level", "expected"),
    [
        ("service_issue", "Critical", Severity.CRITICAL),
        ("service_issue", None, Severity.HIGH),
        ("service_issue", "Informational", Severity.MEDIUM),
        ("security_advisory", "unreviewed-level", Severity.HIGH),
        ("health_advisory", "Warning", Severity.MEDIUM),
        ("planned_maintenance", None, Severity.LOW),
    ],
)
def test_severity_fails_toward_safety(
    event_type: str, level: str | None, expected: Severity
) -> None:
    (signal,) = signals_from_service_health(_collection(_observation(event_type, level=level)))

    assert signal.severity is expected
    expected_category = (
        ReportCategory.SECURITY if event_type == "security_advisory" else ReportCategory.WORKLOAD
    )
    assert signal.category is expected_category


def test_signal_ids_are_stable_within_a_day_and_distinct_per_impact_and_day() -> None:
    first = signals_from_service_health(
        _collection(_observation(impact="a"), _observation(impact="b"))
    )
    later_same_day = signals_from_service_health(
        _collection(
            _observation(impact="a"),
            _observation(impact="b"),
            observed_at=_NOW + timedelta(minutes=5),
        )
    )
    next_day = signals_from_service_health(
        _collection(_observation(impact="a"), observed_at=_NOW + timedelta(days=1))
    )

    assert len({s.signal_id for s in first}) == 2
    assert {s.signal_id for s in first} == {s.signal_id for s in later_same_day}
    assert next_day[0].signal_id not in {s.signal_id for s in first}


def test_event_without_impact_is_scoped_to_the_subscription() -> None:
    (signal,) = signals_from_service_health(_collection(_observation(impact=None)))

    assert signal.resource_ref == "subscription"
    assert signal.evidence_refs == ("event:TRK-1",)


def test_incomplete_collection_is_marked_on_every_signal() -> None:
    (signal,) = signals_from_service_health(_collection(_observation(), complete=False))

    assert signal.metadata["collection_complete"] == "false"
    assert signal.metadata["collection_limitation"] == "result_limit"


class _Reader:
    def __init__(self, *collections: ServiceHealthCollection | Exception) -> None:
        self._items = list(collections)

    async def read_active(self) -> ServiceHealthCollection:
        item = self._items.pop(0) if len(self._items) > 1 else self._items[0]
        if isinstance(item, Exception):
            raise item
        return item


class _Writer:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.recorded: list[ReportSignal] = []
        self.calls = 0
        self._fail_first = fail_first

    async def record_many(self, signals: Sequence[ReportSignal]) -> None:
        self.calls += 1
        if self._fail_first and self.calls == 1:
            raise RuntimeError("store unavailable")
        self.recorded.extend(signals)


async def test_run_once_records_signals_and_reports_incomplete_posture() -> None:
    writer = _Writer()
    job = ServiceHealthSignalJob(
        reader=_Reader(_collection(_observation(), complete=False)), writer=writer
    )

    outcome = await job.run_once()

    assert (outcome.observed, outcome.recorded, outcome.complete) == (1, 1, False)
    assert outcome.limitation == "result_limit"
    assert len(writer.recorded) == 1


async def test_loop_survives_reader_and_writer_failures_until_stopped() -> None:
    writer = _Writer(fail_first=True)
    delays: list[float] = []

    class _Job(ServiceHealthSignalJob):
        async def _wait(self, stop: asyncio.Event, delay: float) -> None:
            delays.append(delay)
            if writer.calls >= 2:
                stop.set()

    job = _Job(
        reader=_Reader(
            _collection(_observation()), RuntimeError("boom"), _collection(_observation())
        ),
        writer=writer,
        interval_seconds=60.0,
    )
    stop = asyncio.Event()

    await asyncio.wait_for(job.run(stop), timeout=5)

    assert writer.calls == 2
    assert len(writer.recorded) == 1
    assert delays == [120.0, 240.0, 60.0]


def test_job_rejects_unsafe_cadence() -> None:
    with pytest.raises(ValueError, match="interval_seconds"):
        ServiceHealthSignalJob(reader=_Reader(_collection()), writer=_Writer(), interval_seconds=1)


def test_unobserved_incomplete_read_records_a_gap_instead_of_a_clear_feed() -> None:
    collection = ServiceHealthCollection(
        observations=(),
        observed_at=_NOW,
        complete=False,
        limitation="source_unavailable",
        attempt_ref="attempt",
    )

    (signal,) = signals_from_service_health(collection)

    assert signal.metadata["rule_id"] == "service-health.source_gap"
    assert signal.severity is Severity.MEDIUM
    assert signals_from_service_health(_collection()) == []


def test_provider_title_whitespace_is_normalized() -> None:
    observation = replace(_observation(), title="line one\n\n  line two\t")

    (signal,) = signals_from_service_health(_collection(observation))

    assert signal.title.endswith("line one line two")


@pytest.mark.parametrize("interval", [float("nan"), float("inf"), 30.0, 7200.0])
def test_job_rejects_non_finite_or_out_of_range_cadence(interval: float) -> None:
    with pytest.raises(ValueError, match="interval_seconds"):
        ServiceHealthSignalJob(
            reader=_Reader(_collection()), writer=_Writer(), interval_seconds=interval
        )


def test_security_advisory_signal_surfaces_as_a_security_assessment_finding() -> None:
    from datetime import timedelta as _td

    from fdai.core.report_feed.models import ReportFeedResult
    from fdai.core.reporting.datasources.security_assessment import _build_from_feed

    result = ReportFeedResult(
        signals=tuple(signals_from_service_health(_collection(_observation())))
    )

    report = _build_from_feed(
        result, scope="subscription", assessed_at=_NOW, freshness_ttl=_td(hours=1)
    )

    assert [entry.rule_id for entry in report.entries] == ["service-health.security_advisory"]


def test_runtime_binding_is_opt_in_and_fails_closed_when_misconfigured() -> None:
    from fdai.runtime.service_health_signals import build_service_health_signal_job

    assert (
        build_service_health_signal_job(environment={}, identity=object(), http_client=object())
        is None
    )
    with pytest.raises(RuntimeError, match="FDAI_SERVICE_HEALTH_SIGNALS_ENABLED"):
        build_service_health_signal_job(
            environment={"FDAI_SERVICE_HEALTH_SIGNALS_ENABLED": "1"},
            identity=object(),
            http_client=object(),
        )
