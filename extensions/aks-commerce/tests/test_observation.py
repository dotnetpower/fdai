from datetime import UTC, datetime, timedelta

from fdai.shared.providers.metric import MetricPoint, StaticMetricProvider
from fdai_service_contracts import (
    AksCommerceEvidenceState,
    AksCommerceSlo,
    AksCommerceWorkload,
)

from fdai_aks_commerce import (
    CommerceMetricBinding,
    MetricCommerceObservationSource,
    WorkloadEvidenceSet,
)

NOW = datetime(2026, 9, 17, tzinfo=UTC)


class _Workloads:
    async def read(self, service_id: str, *, cutoff: datetime) -> WorkloadEvidenceSet:
        assert service_id == "order-fulfillment"
        assert cutoff == NOW
        return WorkloadEvidenceSet(
            workloads=(
                AksCommerceWorkload(
                    workload_id="order-processor",
                    display_name="Order processor",
                    resource_ref="resource:processor",
                    ready=True,
                    revision="revision-1",
                    evidence_state=AksCommerceEvidenceState.COMPLETE,
                ),
            ),
            evidence_refs=("evidence:kubernetes",),
        )


class _Slos:
    async def read(
        self,
        service_id: str,
        *,
        start: datetime,
        end: datetime,
    ) -> tuple[AksCommerceSlo, ...]:
        assert service_id == "order-fulfillment"
        assert end == NOW
        assert start == NOW - timedelta(minutes=5)
        return (
            AksCommerceSlo(
                slo_id="order-fulfillment.availability",
                objective_ratio=0.99,
                observed_ratio=1,
                budget_remaining_ratio=1,
                breached=False,
                state=AksCommerceEvidenceState.COMPLETE,
                source_ref="source:synthetic",
            ),
        )


async def test_metric_source_preserves_previous_and_current_windows() -> None:
    provider = StaticMetricProvider(
        (
            MetricPoint(
                "stream.active_messages",
                NOW - timedelta(minutes=4),
                2,
                {"resource_id": "resource:queue"},
            ),
            MetricPoint(
                "stream.active_messages",
                NOW - timedelta(minutes=1),
                9,
                {"resource_id": "resource:queue"},
            ),
        )
    )
    source = MetricCommerceObservationSource(
        metric_provider=provider,
        metric_bindings=(
            CommerceMetricBinding(
                name="stream.active_messages",
                resource_ref="resource:queue",
                unit="count",
                reduction="last",
                source_ref="source:service-bus",
            ),
        ),
        workload_reader=_Workloads(),
        slo_reader=_Slos(),
        dependency_paths={
            "order-fulfillment": ("order-processor",),
        },
        clock=lambda: NOW,
    )

    frame = await source.collect("order-fulfillment")

    assert frame.metrics[0].previous == 2
    assert frame.metrics[0].current == 9
    assert frame.evidence_gaps == ()
    assert frame.evidence_refs == (
        "evidence:kubernetes",
        "source:service-bus",
        "source:synthetic",
    )


async def test_empty_metric_window_is_explicitly_unavailable() -> None:
    source = MetricCommerceObservationSource(
        metric_provider=StaticMetricProvider(()),
        metric_bindings=(
            CommerceMetricBinding(
                name="stream.active_messages",
                resource_ref="resource:queue",
                unit="count",
                reduction="last",
                source_ref="source:service-bus",
            ),
        ),
        workload_reader=_Workloads(),
        slo_reader=_Slos(),
        dependency_paths={"order-fulfillment": ("order-processor",)},
        clock=lambda: NOW,
    )

    frame = await source.collect("order-fulfillment")

    assert frame.metrics[0].state is AksCommerceEvidenceState.UNAVAILABLE
    assert frame.evidence_gaps == ("metric_empty.stream.active_messages",)
