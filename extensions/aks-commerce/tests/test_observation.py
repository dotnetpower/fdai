import copy
import ssl
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fdai.shared.providers.metric import (
    MetricFailureReason,
    MetricPoint,
    MetricProviderError,
    MetricQuery,
    StaticMetricProvider,
)
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
from fdai_aks_commerce.acceptance import OrderAcceptanceIntent
from fdai_aks_commerce.acceptance_kubernetes import KubernetesOrderAcceptanceReader

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


def test_metric_binding_and_observation_source_validation_guards() -> None:
    with pytest.raises(ValueError, match="reduction must be last or sum"):
        CommerceMetricBinding(
            name="m",
            resource_ref="r",
            unit="count",
            reduction="avg",
            source_ref="s",
        )
    with pytest.raises(ValueError, match="identity must be non-empty"):
        CommerceMetricBinding(
            name="",
            resource_ref="r",
            unit="count",
            reduction="last",
            source_ref="s",
        )
    binding = CommerceMetricBinding(
        name="m",
        resource_ref="r",
        unit="count",
        reduction="last",
        source_ref="s",
    )
    with pytest.raises(ValueError, match="observation window must be in"):
        MetricCommerceObservationSource(
            metric_provider=StaticMetricProvider(()),
            metric_bindings=(binding,),
            workload_reader=_Workloads(),
            slo_reader=_Slos(),
            dependency_paths={},
            window=timedelta(0),
        )
    with pytest.raises(ValueError, match="1 to 32 items"):
        MetricCommerceObservationSource(
            metric_provider=StaticMetricProvider(()),
            metric_bindings=(),
            workload_reader=_Workloads(),
            slo_reader=_Slos(),
            dependency_paths={},
        )
    with pytest.raises(ValueError, match="names must be unique"):
        MetricCommerceObservationSource(
            metric_provider=StaticMetricProvider(()),
            metric_bindings=(binding, binding),
            workload_reader=_Workloads(),
            slo_reader=_Slos(),
            dependency_paths={},
        )


async def test_observation_source_handles_catalog_failures_conflicts_and_db_pressure() -> None:
    class _CatalogWorkloads:
        async def read(self, service_id: str, *, cutoff: datetime) -> WorkloadEvidenceSet:
            return WorkloadEvidenceSet(
                workloads=(
                    AksCommerceWorkload(
                        workload_id="storefront",
                        display_name="Storefront",
                        resource_ref="resource:storefront",
                        ready=True,
                        evidence_state=AksCommerceEvidenceState.COMPLETE,
                    ),
                ),
                evidence_refs=("evidence:k8s",),
            )

    class _CatalogSlos:
        async def read(
            self, service_id: str, *, start: datetime, end: datetime
        ) -> tuple[AksCommerceSlo, ...]:
            return (
                AksCommerceSlo(
                    slo_id="catalog-browse.availability",
                    objective_ratio=0.99,
                    observed_ratio=1.0,
                    budget_remaining_ratio=1.0,
                    breached=False,
                    state=AksCommerceEvidenceState.COMPLETE,
                    source_ref="source:slo",
                ),
            )

    class _MixedProvider:
        async def query(self, query: MetricQuery):
            if query.metric_name == "provider.fail":
                raise MetricProviderError(
                    "provider unavailable", reason=MetricFailureReason.TIMEOUT
                )
            if query.metric_name == "conflict.metric":
                yield MetricPoint(
                    "conflict.metric",
                    NOW - timedelta(minutes=10),
                    1.0,
                    {"resource_id": "resource:storefront"},
                )
            elif query.metric_name == "incomplete.window":
                yield MetricPoint(
                    "incomplete.window",
                    NOW - timedelta(minutes=4),
                    1.0,
                    {"resource_id": "resource:storefront"},
                )
            elif query.metric_name == "database.normalized_ru_consumption":
                yield MetricPoint(
                    "database.normalized_ru_consumption",
                    NOW - timedelta(minutes=4),
                    45.0,
                    {"resource_id": "resource:db"},
                )
                yield MetricPoint(
                    "database.normalized_ru_consumption",
                    NOW - timedelta(minutes=3),
                    50.0,
                    {"resource_id": "resource:db"},
                )
                yield MetricPoint(
                    "database.normalized_ru_consumption",
                    NOW - timedelta(minutes=2),
                    40.0,
                    {"resource_id": "resource:db"},
                )
                yield MetricPoint(
                    "database.normalized_ru_consumption",
                    NOW - timedelta(minutes=1),
                    55.0,
                    {"resource_id": "resource:db"},
                )

    bindings = (
        CommerceMetricBinding("provider.fail", "resource:storefront", "count", "last", "src:1"),
        CommerceMetricBinding("conflict.metric", "resource:storefront", "count", "last", "src:2"),
        CommerceMetricBinding("incomplete.window", "resource:storefront", "count", "last", "src:3"),
        CommerceMetricBinding(
            "database.normalized_ru_consumption", "resource:db", "percent", "sum", "src:4"
        ),
    )
    source = MetricCommerceObservationSource(
        metric_provider=_MixedProvider(),  # type: ignore[arg-type]
        metric_bindings=bindings,
        workload_reader=_CatalogWorkloads(),
        slo_reader=_CatalogSlos(),
        dependency_paths={"catalog-browse": ("storefront",)},
        clock=lambda: NOW,
    )
    frame = await source.collect("catalog-browse")
    assert frame.service_id == "catalog-browse"
    assert frame.order_store_pressure is True
    assert frame.evidence_gaps == (
        "metric_provider.provider.fail.timeout",
        "metric_conflict.conflict.metric",
        "metric_window_incomplete.incomplete.window",
    )

    with pytest.raises(ValueError, match="is unsupported"):
        await source.collect("unknown")

    no_dep_source = MetricCommerceObservationSource(
        metric_provider=StaticMetricProvider(()),
        metric_bindings=(bindings[0],),
        workload_reader=_CatalogWorkloads(),
        slo_reader=_CatalogSlos(),
        dependency_paths={},
        clock=lambda: NOW,
    )
    with pytest.raises(ValueError, match="no dependency path"):
        await no_dep_source.collect("catalog-browse")

    naive_source = MetricCommerceObservationSource(
        metric_provider=StaticMetricProvider(()),
        metric_bindings=(bindings[0],),
        workload_reader=_CatalogWorkloads(),
        slo_reader=_CatalogSlos(),
        dependency_paths={"catalog-browse": ("storefront",)},
        clock=lambda: datetime(2026, 9, 17),
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        await naive_source.collect("catalog-browse")


def _k8s_intent() -> OrderAcceptanceIntent:
    return OrderAcceptanceIntent(
        policy_ref="policy:example",
        resource_ref="resource:deployment",
        service_resource_ref="resource:service",
        cluster_ref="cluster:example",
        namespace="example-store",
        deployment_name="order-api",
        deployment_uid="uid-order",
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(minutes=1),
    )


class _K8sAuth:
    async def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer test"}


def _k8s_base_resources() -> dict[str, Any]:
    return {
        "deployment": {
            "kind": "Deployment",
            "metadata": {
                "uid": "uid-order",
                "name": "order-api",
                "namespace": "example-store",
                "resourceVersion": "1",
                "generation": 1,
            },
            "spec": {"replicas": 1, "template": {"metadata": {"labels": {"app": "order-api"}}}},
            "status": {"observedGeneration": 1, "readyReplicas": 1},
        },
        "service": {
            "kind": "Service",
            "metadata": {
                "uid": "uid-service",
                "name": "order-api",
                "namespace": "example-store",
                "resourceVersion": "1",
            },
            "spec": {"selector": {"app": "order-api"}},
        },
        "slices": {
            "metadata": {},
            "items": [
                {
                    "kind": "EndpointSlice",
                    "metadata": {
                        "namespace": "example-store",
                        "labels": {"kubernetes.io/service-name": "order-api"},
                        "ownerReferences": [
                            {
                                "kind": "Service",
                                "name": "order-api",
                                "uid": "uid-service",
                                "controller": True,
                            }
                        ],
                    },
                    "endpoints": [
                        {"conditions": {"ready": False}},
                        {
                            "conditions": {"ready": True},
                            "targetRef": {
                                "kind": "Pod",
                                "namespace": "example-store",
                                "name": "order-api-pod",
                                "uid": "uid-pod",
                            },
                        },
                        {
                            "conditions": {"ready": True},
                            "targetRef": {
                                "kind": "Pod",
                                "namespace": "example-store",
                                "name": "order-api-pod",
                                "uid": "uid-pod",
                            },
                        },
                    ],
                }
            ],
        },
        "pod": {
            "kind": "Pod",
            "metadata": {
                "namespace": "example-store",
                "name": "order-api-pod",
                "uid": "uid-pod",
                "ownerReferences": [
                    {
                        "kind": "ReplicaSet",
                        "name": "order-api-rs",
                        "uid": "uid-rs",
                        "controller": True,
                    }
                ],
            },
            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
        },
        "replica": {
            "kind": "ReplicaSet",
            "metadata": {
                "namespace": "example-store",
                "name": "order-api-rs",
                "uid": "uid-rs",
                "ownerReferences": [
                    {
                        "kind": "Deployment",
                        "name": "order-api",
                        "uid": "uid-order",
                        "controller": True,
                    }
                ],
            },
        },
        "hpas": {"metadata": {}, "items": []},
    }


async def test_kubernetes_reader_validation_and_endpoint_guards() -> None:
    intent = _k8s_intent()
    tls = ssl.create_default_context()
    with pytest.raises(ValueError, match="exact HTTPS origin"):
        KubernetesOrderAcceptanceReader(
            api_server="http://kubernetes.example.com",
            intent=intent,
            service_name="order-api",
            service_uid="uid-service",
            auth=_K8sAuth(),
            tls=tls,
        )
    with pytest.raises(ValueError, match="exact DNS label"):
        KubernetesOrderAcceptanceReader(
            api_server="https://kubernetes.example.com",
            intent=intent,
            service_name="Bad_Name",
            service_uid="uid-service",
            auth=_K8sAuth(),
            tls=tls,
        )
    with pytest.raises(ValueError, match="Service UID is invalid"):
        KubernetesOrderAcceptanceReader(
            api_server="https://kubernetes.example.com",
            intent=intent,
            service_name="order-api",
            service_uid="-bad",
            auth=_K8sAuth(),
            tls=tls,
        )
    insecure_tls = ssl.create_default_context()
    insecure_tls.check_hostname = False
    with pytest.raises(ValueError, match="TLS verification must remain enabled"):
        KubernetesOrderAcceptanceReader(
            api_server="https://kubernetes.example.com",
            intent=intent,
            service_name="order-api",
            service_uid="uid-service",
            auth=_K8sAuth(),
            tls=insecure_tls,
        )

    def _make_reader(
        res: dict[str, Any],
        *,
        clock_fn: Any = lambda: NOW,
        status_code: int = 200,
        oversized: bool = False,
    ) -> KubernetesOrderAcceptanceReader:
        def handler(request: httpx.Request) -> httpx.Response:
            if status_code != 200:
                return httpx.Response(status_code)
            if oversized:
                return httpx.Response(200, content=b"x" * 270_000)
            if "/deployments/" in request.url.path:
                return httpx.Response(200, json=res["deployment"])
            if "/services/" in request.url.path:
                return httpx.Response(200, json=res["service"])
            if request.url.path.endswith("endpointslices"):
                return httpx.Response(200, json=res["slices"])
            if "/pods/" in request.url.path:
                return httpx.Response(200, json=res["pod"])
            if "/replicasets/" in request.url.path:
                return httpx.Response(200, json=res["replica"])
            return httpx.Response(200, json=res["hpas"])

        return KubernetesOrderAcceptanceReader(
            api_server="https://kubernetes.example.com",
            intent=intent,
            service_name="order-api",
            service_uid="uid-service",
            auth=_K8sAuth(),
            tls=tls,
            transport=httpx.MockTransport(handler),
            clock=clock_fn,
        )

    snap = await _make_reader(_k8s_base_resources()).read()
    assert snap.ready_endpoints == 1

    with pytest.raises(ValueError, match="observation clock must be timezone-aware"):
        await _make_reader(_k8s_base_resources(), clock_fn=lambda: datetime(2026, 9, 17)).read()
    with pytest.raises(ValueError, match="observation is unavailable"):
        await _make_reader(_k8s_base_resources(), status_code=503).read()
    with pytest.raises(ValueError, match="exceeds its bound"):
        await _make_reader(_k8s_base_resources(), oversized=True).read()

    for mutator, match in (
        (
            lambda r: r["deployment"]["metadata"].__setitem__("resourceVersion", ""),
            "resource version is unavailable",
        ),
        (
            lambda r: r["deployment"]["spec"].__setitem__("replicas", -1),
            "count is unknown",
        ),
        (
            lambda r: r["slices"].__setitem__("items", "bad"),
            "list is incomplete",
        ),
        (
            lambda r: r["slices"]["items"][0].__setitem__("endpoints", "bad"),
            "EndpointSlice is incomplete",
        ),
        (
            lambda r: r["slices"]["items"][0]["endpoints"].__setitem__(
                1, {"conditions": {"ready": True}, "targetRef": {"kind": "Node"}}
            ),
            "Pod identity is unavailable",
        ),
        (
            lambda r: r["slices"]["items"][0]["endpoints"][1]["targetRef"].__setitem__(
                "name", "BAD_NAME"
            ),
            "resource name is invalid",
        ),
        (
            lambda r: r["slices"]["items"][0]["endpoints"][1]["targetRef"].__setitem__("uid", ""),
            "Pod UID is unavailable",
        ),
        (
            lambda r: r["pod"]["metadata"].__setitem__("ownerReferences", None),
            "ownership is unavailable",
        ),
        (
            lambda r: r["pod"]["metadata"].__setitem__("ownerReferences", []),
            "controller is ambiguous",
        ),
    ):
        broken = copy.deepcopy(_k8s_base_resources())
        mutator(broken)
        with pytest.raises(ValueError, match=match):
            await _make_reader(broken).read()
