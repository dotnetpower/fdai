from collections.abc import AsyncIterator, Sequence
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fdai.core.investigation import InvestigationRequest
from fdai.core.investigation.contract import AnalyzerFinding
from fdai.delivery import analyzer_tick_cli_composition as composition
from fdai.delivery.analyzer_tick import AnalyzerTarget
from fdai.delivery.analyzer_tick_cli_composition import build_analyzer_coordinator
from fdai.shared.providers.metric import MetricPoint, MetricQuery
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class Metrics:
    called = False

    async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
        self.called = True
        points: tuple[MetricPoint, ...] = ()
        for point in points:
            yield point


class Pod:
    resource_kind = "kubernetes_pod"
    called = False

    async def analyze(
        self, *, resource_ref: str, window_seconds: float
    ) -> Sequence[AnalyzerFinding]:
        self.called = True
        return ()

    async def analyze_recovery(
        self,
        *,
        prior_finding: AnalyzerFinding,
        finding_ref: str,
        window_seconds: float,
    ) -> Sequence[AnalyzerFinding]:
        return ()


async def test_live_pod_composition_does_not_require_an_arm_metric_identity() -> None:
    metric, pod = Metrics(), Pod()
    coordinator = build_analyzer_coordinator(
        metric,
        targets=(
            AnalyzerTarget(
                resource_ref="resource:pod",
                resource_kind="kubernetes_pod",
                resource_type="kubernetes.pod",
            ),
        ),
        pod_analyzer=pod,
        state_store=InMemoryStateStore(),
    )
    report = await coordinator.investigate(
        InvestigationRequest(
            requested_by="test:observer",
            resources=(("resource:pod", "kubernetes_pod"),),
            window_seconds=300,
        )
    )
    assert pod.called
    assert not metric.called
    assert not report.analyzer_errors


@pytest.mark.parametrize("enabled", [False, True])
async def test_availability_discovery_reads_only_explicit_enabled_policy_resources(
    monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    receipts = SimpleNamespace(state_store=InMemoryStateStore(), aclose=AsyncMock())
    settings = SimpleNamespace(
        effective_values_with_revision=AsyncMock(
            return_value=(
                {
                    "detection.resource_availability": {
                        "enabled": enabled,
                        "resource_types": ["compute.web-app"],
                        "max_age_seconds": 300,
                        "resources": {
                            "resource:web": {
                                "resource_type": "compute.web-app",
                                "reference": "policy:test",
                                "expected_state": "running",
                                "planned_stops": [],
                            },
                        },
                    },
                },
                1,
            )
        )
    )
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://test@localhost/test")
    monkeypatch.setattr(composition, "build_receipt_store", lambda: receipts)
    monkeypatch.setattr(composition, "RuntimeSettingsService", lambda **kwargs: settings)
    assert await composition.read_availability_target_policy() == (
        {"resource:web": "compute.web-app"} if enabled else {}
    )
    receipts.aclose.assert_awaited_once()


async def test_invalid_availability_discovery_policy_fails_and_closes_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipts = SimpleNamespace(state_store=InMemoryStateStore(), aclose=AsyncMock())
    settings = SimpleNamespace(
        effective_values_with_revision=AsyncMock(
            return_value=(
                {
                    "detection.resource_availability": {"enabled": "invalid"},
                },
                1,
            )
        )
    )
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://test@localhost/test")
    monkeypatch.setattr(composition, "build_receipt_store", lambda: receipts)
    monkeypatch.setattr(composition, "RuntimeSettingsService", lambda **kwargs: settings)
    with pytest.raises(ValueError):
        await composition.read_availability_target_policy()
    receipts.aclose.assert_awaited_once()


async def test_availability_runs_when_the_same_resources_metric_source_is_held() -> None:
    class Availability(Pod):
        resource_kind = "aks_cluster"

    metric, availability = Metrics(), Availability()
    coordinator = build_analyzer_coordinator(
        metric,
        targets=(
            AnalyzerTarget(
                resource_ref="resource:aks",
                resource_kind="aks_cluster",
                resource_type="kubernetes-cluster",
            ),
        ),
        additional_analyzers=(availability,),
        metric_target_refs=frozenset(),
    )
    report = await coordinator.investigate(
        InvestigationRequest(
            requested_by="test:observer",
            resources=(("resource:aks", "aks_cluster"),),
            window_seconds=300,
        )
    )
    assert availability.called
    assert not metric.called
    assert not report.analyzer_errors
