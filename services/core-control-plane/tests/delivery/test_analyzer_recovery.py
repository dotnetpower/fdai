"""Exact prior fault binding, optional recovery and no healthy-Finding creation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.investigation.contract import AnalyzerFinding, FindingAssessment
from fdai.core.investigation.host_cpu import (
    HOST_CPU_ASSESSOR,
    METRIC_HOST_CPU_PERCENT,
    HostCpuAnalyzer,
)
from fdai.core.investigation.kubernetes_pod_status import (
    POD_STATUS_ASSESSOR,
    POD_STATUS_FAULT_SIGNALS,
)
from fdai.core.investigation.resource_availability import ResourceAvailabilityAnalyzer
from fdai.core.ontology_platform.resource_availability_evidence import (
    RESOURCE_AVAILABILITY_ASSESSOR,
    ResourceAvailabilityEvidence,
    ResourceAvailabilityPolicy,
    ResourceOperationalState,
)
from fdai.core.readiness.finding_state import FINDING_STATE_PREFIX, FindingState, finding_identity
from fdai.delivery.analyzer_recovery import (
    AnalyzerRecoveryStateError,
    RecoveryAwareAnalyzer,
    SupportsAnalyzerRecovery,
)
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.metric import MetricPoint, StaticMetricProvider
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
REF = "scope-example/resource-group/example/compute/example"
KIND = "virtual_machine"
SIGNAL = "host_cpu"
IDENTITY = finding_identity(KIND, REF, SIGNAL)
KEY = FINDING_STATE_PREFIX + IDENTITY


def _state(**changes) -> FindingState:
    data = {
        "finding_id": IDENTITY,
        "revision": 3,
        "notification_version": 1,
        "notification_reason": "opened",
        "notification_changed_at": NOW - timedelta(minutes=10),
        "resource_ref": REF,
        "resource_kind": KIND,
        "signal": SIGNAL,
        "severity": Severity.HIGH,
        "status": "active",
        "observation": "Observed host CPU exceeded the configured threshold.",
        "observation_key": "observation:example",
        "observation_digest": "example-digest",
        "first_seen_at": NOW - timedelta(minutes=10),
        "occurred_at": NOW - timedelta(minutes=10),
        "recorded_at": NOW - timedelta(minutes=10),
        "current_state": "cpu_threshold_observed",
        "evidence_complete": True,
        "evidence_state": "complete",
        "recovery_closed": False,
        "assessed_by": HOST_CPU_ASSESSOR,
        "evidence_refs": ("observation:cpu-example",),
        "evidence_gaps": (),
        "publication": "published",
    }
    return FindingState.model_validate({**data, **changes})


def _healthy_analyzer() -> HostCpuAnalyzer:
    points = tuple(
        MetricPoint(
            METRIC_HOST_CPU_PERCENT,
            NOW - timedelta(minutes=minute),
            20,
            {"resource_id": REF},
        )
        for minute in range(5)
    )
    return HostCpuAnalyzer(StaticMetricProvider(points), wall_clock=lambda: NOW)


async def _store(state=None) -> InMemoryStateStore:
    store = InMemoryStateStore()
    if state is not None:
        await store.write_state(KEY, state.model_dump(mode="json"))
    return store


async def test_no_prior_fault_never_creates_a_healthy_finding() -> None:
    wrapper = RecoveryAwareAnalyzer(_healthy_analyzer(), await _store(), (SIGNAL,))
    assert wrapper.resource_kind == KIND
    assert isinstance(_healthy_analyzer(), SupportsAnalyzerRecovery)
    assert not await wrapper.analyze(resource_ref=REF, window_seconds=300)


async def test_real_cpu_leaf_recovers_only_the_exact_persisted_active_finding() -> None:
    store = await _store(_state())
    wrapper = RecoveryAwareAnalyzer(_healthy_analyzer(), store, (SIGNAL,))
    (finding,) = await wrapper.analyze(resource_ref=REF, window_seconds=300)
    assert finding.assessment.recovery_closed is True
    assert IDENTITY in finding.evidence_refs
    assert finding.metadata["recovery_finding_ref"] == IDENTITY
    assert finding.metadata["recovery_prior_revision"] == "3"
    assert finding.metadata["current_state"] == "cpu_below_threshold"
    assert (await store.read_state(KEY))["status"] == "active"
    assert finding.remediation_ref is None


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "resolved", "recovery_closed": True},
        {"evidence_complete": False},
        {"evidence_state": "incomplete"},
        {"evidence_gaps": ("metrics_missing",)},
        {"evidence_refs": ()},
        {"assessed_by": "unverified"},
        {"current_state": "unknown"},
        {"current_state": "metrics_missing"},
        {"publication": "publish_uncertain"},
    ],
)
async def test_resolved_gap_or_unverified_rows_cannot_become_prior_faults(changes) -> None:
    wrapper = RecoveryAwareAnalyzer(_healthy_analyzer(), await _store(_state(**changes)), (SIGNAL,))
    assert not await wrapper.analyze(resource_ref=REF, window_seconds=300)


@pytest.mark.parametrize(
    "changes",
    [
        {"finding_id": "another-finding"},
        {"resource_ref": "another-resource"},
        {"resource_kind": "another-kind"},
        {"signal": "resource_availability"},
    ],
)
async def test_stored_identity_cannot_widen_the_target_or_signal(changes) -> None:
    wrapper = RecoveryAwareAnalyzer(_healthy_analyzer(), await _store(_state(**changes)), (SIGNAL,))
    with pytest.raises(AnalyzerRecoveryStateError, match="identity"):
        await wrapper.analyze(resource_ref=REF, window_seconds=300)


async def test_corrupt_state_is_a_partial_error_not_healthy() -> None:
    store = await _store()
    await store.write_state(KEY, {"private": "do-not-render"})
    wrapper = RecoveryAwareAnalyzer(_healthy_analyzer(), store, (SIGNAL,))
    with pytest.raises(AnalyzerRecoveryStateError, match="state is invalid") as error:
        await wrapper.analyze(resource_ref=REF, window_seconds=300)
    assert "do-not-render" not in str(error.value)


async def test_fresh_actual_fault_does_not_read_prior_state_or_query_recovery() -> None:
    fault = AnalyzerFinding(
        REF,
        KIND,
        SIGNAL,
        "CPU threshold observed.",
        Severity.HIGH,
        NOW,
        assessment=FindingAssessment(HOST_CPU_ASSESSOR, True, False, "cpu_threshold_observed"),
    )

    class Analyzer:
        resource_kind = KIND

        async def analyze(self, **kwargs):
            return (fault,)

        async def analyze_recovery(self, **kwargs):
            raise AssertionError("fresh fault MUST NOT query recovery")

    class Store(InMemoryStateStore):
        async def read_state(self, key):
            raise AssertionError("fresh fault MUST NOT read recovery state")

    wrapper = RecoveryAwareAnalyzer(Analyzer(), Store(), (SIGNAL,))
    (finding,) = await wrapper.analyze(resource_ref=REF, window_seconds=300)
    assert finding.assessment == fault.assessment
    assert finding.metadata["current_state"] == "cpu_threshold_observed"


async def test_analyzer_without_optional_method_keeps_existing_behavior() -> None:
    class Analyzer:
        resource_kind = KIND

        async def analyze(self, **kwargs):
            return ()

    analyzer = Analyzer()
    assert not isinstance(analyzer, SupportsAnalyzerRecovery)
    assert not await RecoveryAwareAnalyzer(analyzer, await _store(_state()), (SIGNAL,)).analyze(
        resource_ref=REF, window_seconds=300
    )


async def test_prior_state_change_during_recovery_fails_closed() -> None:
    store = await _store(_state())
    delegate = _healthy_analyzer()

    class Analyzer:
        resource_kind = KIND

        async def analyze(self, **kwargs):
            return ()

        async def analyze_recovery(self, **kwargs):
            await store.write_state(KEY, _state(revision=4).model_dump(mode="json"))
            return await delegate.analyze_recovery(**kwargs)

    wrapper = RecoveryAwareAnalyzer(Analyzer(), store, (SIGNAL,))
    with pytest.raises(AnalyzerRecoveryStateError, match="changed during"):
        await wrapper.analyze(resource_ref=REF, window_seconds=300)


async def test_missing_current_metrics_do_not_close_a_prior_fault() -> None:
    wrapper = RecoveryAwareAnalyzer(
        HostCpuAnalyzer(StaticMetricProvider(()), wall_clock=lambda: NOW),
        await _store(_state()),
        (SIGNAL,),
    )
    (finding,) = await wrapper.analyze(resource_ref=REF, window_seconds=300)
    assert finding.assessment.status == "metrics_missing"
    assert finding.assessment.recovery_closed is None


def test_unknown_recovery_contract_is_not_guessed() -> None:
    with pytest.raises(ValueError, match="reviewed"):
        RecoveryAwareAnalyzer(_healthy_analyzer(), InMemoryStateStore(), ("unknown",))


async def test_real_availability_leaf_recovers_an_exact_observed_stop() -> None:
    signal = "resource_availability"
    identity = finding_identity(KIND, REF, signal)
    state = _state(
        finding_id=identity,
        signal=signal,
        current_state="stop_observed",
        assessed_by=RESOURCE_AVAILABILITY_ASSESSOR,
        observation="Resource was observed stopped.",
        severity=Severity.MEDIUM,
    )
    store = await _store()
    await store.write_state(FINDING_STATE_PREFIX + identity, state.model_dump(mode="json"))

    class Source:
        async def observe(self, **kwargs):
            return ResourceAvailabilityEvidence(
                resource_ref=REF,
                resource_type="compute.vm",
                scope_ref="resource-scope:example",
                state=ResourceOperationalState.RUNNING,
                observed_at=NOW,
                recorded_at=NOW,
                source_revision="example-snapshot",
                evidence_ref="inventory:example:state",
            )

    leaf = ResourceAvailabilityAnalyzer(
        resource_kind=KIND,
        resource_type="compute.vm",
        scope_ref="resource-scope:example",
        source=Source(),
        policy=ResourceAvailabilityPolicy(frozenset({"compute.vm"})),
        wall_clock=lambda: NOW,
    )
    (finding,) = await RecoveryAwareAnalyzer(leaf, store, (signal,)).analyze(
        resource_ref=REF, window_seconds=300
    )
    assert finding.assessment.recovery_closed is True
    assert finding.assessment.status == "running_observed"
    assert identity in finding.evidence_refs


async def test_state_read_failure_is_not_a_healthy_empty_result() -> None:
    class Store(InMemoryStateStore):
        async def read_state(self, key):
            raise RuntimeError("private-provider-details")

    wrapper = RecoveryAwareAnalyzer(_healthy_analyzer(), Store(), (SIGNAL,))
    with pytest.raises(AnalyzerRecoveryStateError, match="unavailable") as error:
        await wrapper.analyze(resource_ref=REF, window_seconds=300)
    assert "private-provider-details" not in str(error.value)


@pytest.mark.parametrize("signal", sorted(POD_STATUS_FAULT_SIGNALS))
async def test_grounded_pod_fault_can_recover_when_prior_optional_logs_were_missing(signal) -> None:
    identity = finding_identity("kubernetes_pod", REF, signal)
    state = _state(
        finding_id=identity,
        resource_kind="kubernetes_pod",
        signal=signal,
        current_state=signal,
        assessed_by=POD_STATUS_ASSESSOR,
        observation="Kubernetes API status established the Pod fault.",
        evidence_complete=False,
        evidence_state="incomplete",
        evidence_refs=("kubernetes-api:example:status",),
        evidence_gaps=("pod_logs_unavailable",),
    )
    store = await _store()
    await store.write_state(FINDING_STATE_PREFIX + identity, state.model_dump(mode="json"))

    class PodAdapter:
        resource_kind = "kubernetes_pod"

        async def analyze(self, **kwargs):
            return ()

        async def analyze_recovery(self, *, prior_finding, finding_ref, window_seconds):
            assert prior_finding.signal == signal
            assert prior_finding.assessment.evidence_complete is False
            assert prior_finding.assessment.evidence_gaps == ("pod_logs_unavailable",)
            assert prior_finding.assessment.status == signal
            return (
                AnalyzerFinding(
                    REF,
                    self.resource_kind,
                    signal,
                    "Fresh complete Pod Ready evidence.",
                    prior_finding.severity,
                    NOW,
                    evidence_refs=(finding_ref, "kubernetes-api:example:ready"),
                    assessment=FindingAssessment(
                        POD_STATUS_ASSESSOR,
                        True,
                        True,
                        signal,
                        "pod_ready_after_fault",
                    ),
                ),
            )

    (finding,) = await RecoveryAwareAnalyzer(
        PodAdapter(),
        store,
        POD_STATUS_FAULT_SIGNALS,
    ).analyze(resource_ref=REF, window_seconds=300)
    assert finding.assessment.recovery_closed is True
    assert finding.assessment.evidence_complete
    assert finding.metadata["recovery_finding_ref"] == identity
    assert finding.metadata["recovery_prior_revision"] == "3"


@pytest.mark.parametrize(
    "changes",
    [
        {"current_state": "insufficient_evidence"},
        {"current_state": "conflicting_evidence"},
        {"current_state": "stale_evidence"},
        {"current_state": "rollout_replacement"},
        {"assessed_by": "unverified"},
        {"evidence_state": "conflicting"},
    ],
)
async def test_pod_recovery_still_rejects_non_fault_or_untrusted_prior(changes) -> None:
    signal = "pod_oom_killed"
    identity = finding_identity("kubernetes_pod", REF, signal)
    state = _state(
        **{
            "finding_id": identity,
            "resource_kind": "kubernetes_pod",
            "signal": signal,
            "current_state": signal,
            "assessed_by": POD_STATUS_ASSESSOR,
            **changes,
        }
    )
    store = await _store()
    await store.write_state(FINDING_STATE_PREFIX + identity, state.model_dump(mode="json"))

    class PodAdapter:
        resource_kind = "kubernetes_pod"

        async def analyze(self, **kwargs):
            return ()

        async def analyze_recovery(self, **kwargs):
            raise AssertionError("unverified prior MUST NOT query recovery")

    assert not await RecoveryAwareAnalyzer(
        PodAdapter(),
        store,
        POD_STATUS_FAULT_SIGNALS,
    ).analyze(resource_ref=REF, window_seconds=300)
