"""Operational Kubernetes capacity evidence adapter tests."""

from __future__ import annotations

from fdai.delivery.kubernetes.event_evidence import KubernetesCapacityEventEvidenceCollector


async def test_operational_capacity_collector_uses_exact_namespace() -> None:
    namespaces: list[str] = []

    async def query(namespace: str) -> dict[str, object]:
        namespaces.append(namespace)
        return {"evidence_complete": True, "findings": [{"decision": "hold"}]}

    evidence = await KubernetesCapacityEventEvidenceCollector(query).collect_payload(
        {
            "resource_type": "kubernetes.namespace",
            "resource_id": "kubernetes.namespace/example-app",
        }
    )

    assert namespaces == ["example-app"]
    assert evidence == {
        "observe.kubernetes.capacity": {
            "status": "available",
            "payload": {"evidence_complete": True, "findings": [{"decision": "hold"}]},
        }
    }


async def test_operational_capacity_collector_ignores_other_resource_types() -> None:
    async def query(namespace: str) -> dict[str, object]:
        raise AssertionError(namespace)

    evidence = await KubernetesCapacityEventEvidenceCollector(query).collect_payload(
        {"resource_type": "compute.vm", "resource_id": "compute.vm/example"}
    )

    assert evidence == {}


async def test_operational_capacity_collector_bounds_provider_failures_and_size() -> None:
    async def fail(namespace: str) -> dict[str, object]:
        raise RuntimeError(namespace)

    failed = await KubernetesCapacityEventEvidenceCollector(fail).collect_payload(
        {
            "resource_type": "kubernetes.namespace",
            "resource_id": "kubernetes.namespace/example-app",
        }
    )

    async def oversized(namespace: str) -> dict[str, object]:
        del namespace
        return {"body": "x" * 128}

    over_limit = await KubernetesCapacityEventEvidenceCollector(
        oversized,
        max_bytes=32,
    ).collect_payload(
        {
            "resource_type": "kubernetes.namespace",
            "resource_id": "kubernetes.namespace/example-app",
        }
    )

    assert failed == {
        "observe.kubernetes.capacity": {"status": "unavailable", "reason": "provider_error"}
    }
    assert over_limit == {
        "observe.kubernetes.capacity": {
            "status": "unavailable",
            "reason": "response_over_limit",
        }
    }
