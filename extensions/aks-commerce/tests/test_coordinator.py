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
from fdai_aks_commerce.acceptance import (
    OrderAcceptanceAnalyzer,
    OrderAcceptanceEvidence,
    OrderAcceptanceIntent,
    OrderAcceptanceProbe,
    evaluate_order_acceptance,
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


def _acceptance_intent() -> OrderAcceptanceIntent:
    return OrderAcceptanceIntent(
        policy_ref="policy:example-acceptance",
        resource_ref=TARGET,
        service_resource_ref="resource:example-service",
        cluster_ref="cluster:example",
        namespace="example-store",
        deployment_name="order-api",
        deployment_uid="uid-order",
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(minutes=5),
    )


def _acceptance_evidence() -> OrderAcceptanceEvidence:
    intent = _acceptance_intent()
    return OrderAcceptanceEvidence(
        resource_ref=intent.resource_ref,
        service_resource_ref=intent.service_resource_ref,
        cluster_ref=intent.cluster_ref,
        namespace=intent.namespace,
        deployment_name=intent.deployment_name,
        deployment_uid=intent.deployment_uid,
        resource_version="version-1",
        observed_at=NOW,
        desired_replicas=0,
        ready_replicas=0,
        ready_endpoints=0,
        probes=tuple(
            OrderAcceptanceProbe(
                evidence_ref=f"probe:example-{index}",
                observed_at=NOW - timedelta(seconds=2 - index),
                accepted=False,
                authorization_ref="authority:example-orders",
            )
            for index in range(2)
        ),
        kubernetes_evidence_ref="observation:example-kubernetes",
        verification_ref="receipt:example",
        complete=True,
        maintenance_active=False,
        hpa_managed=False,
        competing_writer=False,
        sample=False,
    )


class _AcceptanceSource:
    def __init__(self) -> None:
        self.evidence = _acceptance_evidence()

    async def observe(self, intent: OrderAcceptanceIntent) -> OrderAcceptanceEvidence:
        assert intent.resource_ref == TARGET
        return self.evidence


class _AcceptanceVerifier:
    def __init__(self, digest: str) -> None:
        self.digest = digest
        self.calls = 0

    async def verify(self, *, verification_ref: str, evidence_digest: str) -> bool:
        self.calls += 1
        return verification_ref == "receipt:example" and evidence_digest == self.digest


def _acceptance_analyzer(
    source: _AcceptanceSource, verifier: _AcceptanceVerifier
) -> OrderAcceptanceAnalyzer:
    return OrderAcceptanceAnalyzer(
        intent=_acceptance_intent(),
        source=source,
        verifier=verifier,
        resource_kind="kubernetes.deployment",
        severity=Severity.HIGH,
        clock=lambda: source.evidence.observed_at,
    )


async def test_acceptance_failure_keeps_synthetic_provenance_and_inert_candidate() -> None:
    source = _AcceptanceSource()
    reduced = evaluate_order_acceptance(
        _acceptance_intent(), source.evidence, now=NOW, window_seconds=30
    )
    verifier = _AcceptanceVerifier(reduced.evidence_digest)
    analyzer = _acceptance_analyzer(source, verifier)

    findings = await analyzer.analyze(resource_ref=TARGET, window_seconds=30)
    assessment = await analyzer.assess(resource_ref=TARGET, window_seconds=30)

    assert len(findings) == 1
    assert findings[0].signal == "aks_commerce.order_acceptance_unavailable"
    assert findings[0].remediation_ref is None
    assert all(probe.synthetic_traffic for probe in source.evidence.probes)
    assert assessment.proposal is not None
    assert assessment.proposal.action_type == "ops.scale-out"
    assert assessment.proposal.execution_authority is False
    assert assessment.proposal.arguments["replica_count"] == 1
    assert assessment.proposal.arguments["target_uid"] == "uid-order"
    assert assessment.proposal.arguments["resource_version"] == "version-1"
    assert verifier.calls == 2


@pytest.mark.parametrize(
    "defect",
    [
        "sample",
        "incomplete",
        "wrong_uid",
        "stale",
        "unknown",
        "duplicate",
        "reordered",
        "insufficient",
        "ready_endpoint",
    ],
)
async def test_unqualified_acceptance_is_withheld_before_receipt_verification(defect: str) -> None:
    source = _AcceptanceSource()
    original = source.evidence
    changes: dict[str, Any] = {
        "sample": {"sample": True},
        "incomplete": {"complete": False},
        "wrong_uid": {"deployment_uid": "another-uid"},
        "stale": {
            "probes": (
                replace(original.probes[0], observed_at=NOW - timedelta(minutes=2)),
                original.probes[1],
            )
        },
        "unknown": {"probes": (replace(original.probes[0], accepted=None), original.probes[1])},
        "duplicate": {"probes": (original.probes[0], original.probes[0])},
        "reordered": {"probes": tuple(reversed(original.probes))},
        "insufficient": {"probes": original.probes[:1]},
        "ready_endpoint": {"ready_endpoints": 1},
    }
    source.evidence = replace(original, **changes[defect])
    verifier = _AcceptanceVerifier("not-admitted")

    with pytest.raises(ValueError, match="not qualified"):
        await _acceptance_analyzer(source, verifier).analyze(resource_ref=TARGET, window_seconds=30)
    assert verifier.calls == 0


@pytest.mark.parametrize("guard", ["maintenance_active", "hpa_managed", "competing_writer"])
@pytest.mark.parametrize("value", [True, None])
def test_acceptance_failure_does_not_override_unknown_or_active_writer(
    guard: str, value: bool | None
) -> None:
    evidence = replace(_acceptance_evidence(), **{guard: value})
    result = evaluate_order_acceptance(_acceptance_intent(), evidence, now=NOW, window_seconds=30)

    assert result.status == "unavailable"
    assert result.proposal is None


async def test_altered_observation_cannot_reuse_acceptance_receipt() -> None:
    source = _AcceptanceSource()
    original = evaluate_order_acceptance(
        _acceptance_intent(), source.evidence, now=NOW, window_seconds=30
    )
    source.evidence = replace(source.evidence, resource_version="version-2")
    verifier = _AcceptanceVerifier(original.evidence_digest)

    with pytest.raises(ValueError, match="receipt is not verified"):
        await _acceptance_analyzer(source, verifier).analyze(resource_ref=TARGET, window_seconds=30)


def test_positive_acceptance_does_not_claim_fulfillment_or_incident_closure() -> None:
    original = _acceptance_evidence()
    evidence = replace(
        original,
        desired_replicas=1,
        ready_replicas=1,
        ready_endpoints=1,
        probes=tuple(replace(probe, accepted=True) for probe in original.probes),
    )
    result = evaluate_order_acceptance(_acceptance_intent(), evidence, now=NOW, window_seconds=30)

    assert result.status == "accepting"
    assert result.proposal is None


def test_expired_operating_intent_is_held() -> None:
    intent = _acceptance_intent()
    result = evaluate_order_acceptance(
        intent, _acceptance_evidence(), now=intent.valid_until, window_seconds=30
    )

    assert result.status == "held"
    assert result.evidence_gaps == ("intent_not_current",)


async def test_acceptance_observations_open_one_canonical_incident() -> None:
    source = _AcceptanceSource()
    verifier = _AcceptanceVerifier("not-admitted")
    analyzer = _acceptance_analyzer(source, verifier)
    bus = _Bus()
    runner = AnalyzerTickRunner(
        coordinator=InvestigationCoordinator(
            analyzers=(analyzer,),
            wall_clock=lambda: source.evidence.observed_at,
        ),
        event_bus=bus,
        publication_ledger=PostgresAnalyzerPublicationLedger(store=ConditionalStore()),
        window_seconds=30,
        publication_window_seconds=5,
        clock=lambda: source.evidence.observed_at,
    )
    targets = (AnalyzerTarget(resource_ref=TARGET, resource_kind=analyzer.resource_kind),)
    registry = IncidentRegistry(state_store=InMemoryStateStore())
    workflow = IncidentLifecycleWorkflow(registry=registry, allowed_agent_principals={"Heimdall"})

    async def capture(candidate: dict[str, Any]) -> bool:
        return (
            await open_detected_incident_candidate(
                workflow=workflow,
                candidate=candidate,
                policy=IncidentAutoOpenPolicy(),
            )
            is not None
        )

    huginn = Huginn()
    heimdall = Heimdall(rate_threshold=2, rate_window=30, incident_candidate_hook=capture)
    for tick in range(3):
        base = _acceptance_evidence()
        offset = timedelta(seconds=5 * tick)
        source.evidence = replace(
            base,
            observed_at=NOW + offset,
            probes=tuple(
                replace(
                    probe,
                    observed_at=probe.observed_at + offset,
                    evidence_ref=f"{probe.evidence_ref}-{tick}",
                )
                for probe in base.probes
            ),
        )
        verifier.digest = evaluate_order_acceptance(
            _acceptance_intent(),
            source.evidence,
            now=source.evidence.observed_at,
            window_seconds=30,
        ).evidence_digest
        report = await runner.run_once(targets)
        assert report.published == 1
        assert not report.failed
        replay = await runner.run_once(targets)
        assert replay.duplicates_suppressed == 1
        normalized = await huginn.ingest(bus.calls[-1])
        assert normalized is not None
        await heimdall.on_typed_message("object.event", normalized)
        if tick == 0:
            assert not registry.snapshot()

    assert len(registry.snapshot()) == 1
    assert len(bus.calls) == 3
    assert len({payload["correlation_id"] for payload in bus.calls}) == 1
    assert all(payload["mode"] == "shadow" for payload in bus.calls)
    assert all(payload["payload"]["remediation_ref"] is None for payload in bus.calls)


def test_resource_refresh_does_not_retime_the_same_failed_orders() -> None:
    base = _acceptance_evidence()
    first = evaluate_order_acceptance(_acceptance_intent(), base, now=NOW, window_seconds=30)
    refreshed = replace(base, observed_at=NOW + timedelta(seconds=5), resource_version="version-2")
    later = evaluate_order_acceptance(
        _acceptance_intent(),
        refreshed,
        now=refreshed.observed_at,
        window_seconds=30,
    )

    assert first.observed_at == later.observed_at
    assert first.evidence_digest != later.evidence_digest
