from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.agents import Heimdall, Huginn
from fdai.core.incident import (
    IncidentAutoOpenPolicy,
    IncidentLifecycleWorkflow,
    IncidentRegistry,
    open_detected_incident_candidate,
)
from fdai.core.investigation import InvestigationCoordinator
from fdai.delivery.analyzer_tick import AnalyzerTarget, AnalyzerTickRunner
from fdai.delivery.persistence.postgres_analyzer_publication import (
    PostgresAnalyzerPublicationLedger,
)
from fdai.shared.contracts.models import IncidentSeverity, Mode, Severity
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts import (
    AksCommerceEvidenceState,
    AksCommerceMetric,
    AksCommerceSlo,
    AksCommerceWorkload,
)
from tests.delivery.publication_store import ConditionalStore

from fdai_aks_commerce import (
    AksCommerceAnalyzer,
    AksCommerceCoordinator,
    AksCommerceEvidenceFrame,
)

NOW = datetime(2026, 9, 17, tzinfo=UTC)
TARGET = "resource:example-product-api"


def _frame(*, available: bool = False) -> AksCommerceEvidenceFrame:
    return AksCommerceEvidenceFrame(
        service_id="catalog-browse",
        observed_at=NOW,
        window_start=NOW - timedelta(seconds=20),
        window_end=NOW,
        dependency_path=("product-api",),
        workloads=(
            AksCommerceWorkload(
                workload_id="product-api",
                display_name="Product API",
                resource_ref=TARGET,
                ready=available,
                evidence_state=AksCommerceEvidenceState.COMPLETE,
            ),
        ),
        slos=(
            AksCommerceSlo(
                slo_id="catalog-browse.availability",
                objective_ratio=0.99,
                observed_ratio=float(available),
                budget_remaining_ratio=float(available),
                breached=not available,
                state=AksCommerceEvidenceState.COMPLETE,
                source_ref="source:example-slo",
            ),
        ),
        metrics=(
            AksCommerceMetric(
                name="synthetic.catalog.availability",
                unit="ratio",
                current=float(available),
                observed_at=NOW,
                source_ref="source:example-availability",
                state=AksCommerceEvidenceState.COMPLETE,
            ),
        ),
        evidence_refs=("evidence:example-catalog",),
    )


class _Source:
    def __init__(self, frame: AksCommerceEvidenceFrame) -> None:
        self.frame = frame
        self.calls = 0

    async def collect(self, service_id: str) -> AksCommerceEvidenceFrame:
        assert service_id == "catalog-browse"
        self.calls += 1
        return self.frame


def _analyzer(
    source: _Source, *, clock: Callable[[], datetime] = lambda: NOW
) -> AksCommerceAnalyzer:
    return AksCommerceAnalyzer(
        coordinator=AksCommerceCoordinator(source=source, store=InMemoryStateStore()),
        resource_kind="kubernetes.deployment",
        service_by_resource={TARGET: "catalog-browse"},
        severity=Severity.HIGH,
        clock=clock,
    )


async def test_complete_failure_becomes_evidence_only_finding() -> None:
    source = _Source(_frame())
    analyzer = _analyzer(source)

    first = await analyzer.analyze(resource_ref=TARGET, window_seconds=30)
    replay = await analyzer.analyze(resource_ref=TARGET, window_seconds=30)

    assert first == replay
    assert len(first) == 1
    assert first[0].resource_ref == TARGET
    assert first[0].signal == "aks_commerce.catalog_unavailable"
    assert first[0].severity is Severity.HIGH
    assert first[0].occurred_at == NOW
    assert first[0].remediation_ref is None
    assert first[0].assessment is not None
    assert first[0].assessment.recovery_closed is None
    assert first[0].evidence_refs[0].startswith("sha256:")


async def test_healthy_observation_does_not_emit_incident_trigger() -> None:
    assert (
        await _analyzer(_Source(_frame(available=True))).analyze(
            resource_ref=TARGET, window_seconds=30
        )
        == ()
    )


async def test_unknown_target_is_rejected_before_collection() -> None:
    source = _Source(_frame())
    with pytest.raises(ValueError, match="target is not configured"):
        await _analyzer(source).analyze(resource_ref="resource:other", window_seconds=30)
    assert source.calls == 0


@pytest.mark.parametrize(
    "failure",
    ["held", "synthetic", "metric_synthetic", "wrong_target", "stale", "future", "old_metric"],
)
async def test_unqualified_observation_never_becomes_a_finding(failure: str) -> None:
    frame = _frame()
    if failure == "held":
        frame = replace(frame, evidence_gaps=("observation_missing",))
    elif failure == "synthetic":
        frame = replace(frame, synthetic=True)
    elif failure == "metric_synthetic":
        frame = replace(frame, metrics=(frame.metrics[0].model_copy(update={"synthetic": True}),))
    elif failure == "wrong_target":
        frame = replace(
            frame,
            workloads=(frame.workloads[0].model_copy(update={"resource_ref": "resource:other"}),),
        )
    elif failure in {"stale", "future"}:
        offset = timedelta(minutes=-2 if failure == "stale" else 2)
        frame = replace(
            frame,
            observed_at=NOW + offset,
            window_start=frame.window_start + offset,
            window_end=NOW + offset,
        )
    else:
        frame = replace(
            frame,
            metrics=(
                frame.metrics[0].model_copy(update={"observed_at": NOW - timedelta(hours=1)}),
            ),
        )

    with pytest.raises(ValueError, match="AKS commerce assessment"):
        await _analyzer(_Source(frame)).analyze(resource_ref=TARGET, window_seconds=30)


class _Bus(InMemoryEventBus):
    def __init__(self, *, fail: bool = False) -> None:
        super().__init__()
        self.calls: list[Mapping[str, Any]] = []
        self.fail = fail

    async def publish(self, topic: str, key: str, payload: Mapping[str, Any]) -> PublishReceipt:
        self.calls.append(payload)
        receipt = await super().publish(topic, key, payload)
        if self.fail:
            raise TimeoutError("broker acknowledgement unavailable")
        return receipt


def _runner(source: _Source, bus: _Bus) -> AnalyzerTickRunner:
    return AnalyzerTickRunner(
        coordinator=InvestigationCoordinator(
            analyzers=(_analyzer(source, clock=lambda: source.frame.observed_at),),
            wall_clock=lambda: source.frame.observed_at,
        ),
        event_bus=bus,
        publication_ledger=PostgresAnalyzerPublicationLedger(store=ConditionalStore()),
        window_seconds=30,
        publication_window_seconds=5,
        clock=lambda: source.frame.observed_at,
    )


async def test_distinct_observations_open_one_incident_without_execution() -> None:
    source = _Source(_frame())
    bus = _Bus()
    runner = _runner(source, bus)
    targets = (AnalyzerTarget(resource_ref=TARGET, resource_kind="kubernetes.deployment"),)
    registry = IncidentRegistry(state_store=InMemoryStateStore())
    workflow = IncidentLifecycleWorkflow(registry=registry, allowed_agent_principals={"Heimdall"})

    async def capture(candidate: dict[str, Any]) -> bool:
        result = await open_detected_incident_candidate(
            workflow=workflow, candidate=candidate, policy=IncidentAutoOpenPolicy()
        )
        return result is not None

    huginn = Huginn()
    heimdall = Heimdall(rate_threshold=2, rate_window=30, incident_candidate_hook=capture)
    for tick in range(3):
        offset = timedelta(seconds=5 * tick)
        source.frame = replace(
            _frame(),
            observed_at=NOW + offset,
            window_end=NOW + offset,
            window_start=NOW + offset - timedelta(seconds=20),
            metrics=(_frame().metrics[0].model_copy(update={"observed_at": NOW + offset}),),
        )
        report = await runner.run_once(targets)
        assert not report.failed
        assert report.published == 1
        replay = await runner.run_once(targets)
        assert replay.duplicates_suppressed == 1
        payload = bus.calls[-1]
        assert payload["mode"] == Mode.SHADOW.value
        assert payload["payload"]["remediation_ref"] is None
        normalized = await huginn.ingest(payload)
        assert normalized is not None
        await heimdall.on_typed_message("object.event", normalized)
        if tick == 0:
            assert not registry.snapshot()

    incidents = tuple(registry.snapshot().values())
    assert len(incidents) == 1
    assert incidents[0].severity is IncidentSeverity.SEV2
    assert len(incidents[0].member_event_ids) == 2
    assert len(bus.calls) == 3
    assert len({payload["correlation_id"] for payload in bus.calls}) == 1
    assert len({payload["event_id"] for payload in bus.calls}) == 3


async def test_uncertain_publication_is_not_retried_without_reconciliation() -> None:
    source = _Source(_frame())
    bus = _Bus(fail=True)
    runner = _runner(source, bus)
    targets = (AnalyzerTarget(resource_ref=TARGET, resource_kind="kubernetes.deployment"),)

    first = await runner.run_once(targets)
    replay = await runner.run_once(targets)

    assert first.failed
    assert first.uncertain == 1
    assert replay.uncertain == 1
    assert len(bus.calls) == 1
