"""Tests for Kubernetes evaluation evidence ontology observation."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai_evaluation_sdk import EvaluationTask, ResourceLimits, TargetRef

from fdai.delivery.evaluation.diagnostic_functions import DiagnosticFunctionExecutor
from fdai.delivery.evaluation.kubernetes_ontology import KubernetesOntologyEvidenceObserver
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.runtime.catalog_ontology import load_diagnostic_catalog_projection
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

_ROOT = Path(__file__).resolve().parents[2]


def _cluster_identity(name: str) -> str:
    return f"sha256:{hashlib.sha256(name.encode('utf-8')).hexdigest()}"


_CLUSTER = _cluster_identity("example-cluster")


def _namespace_ref(cluster: str = _CLUSTER) -> str:
    return f"kubernetes.cluster:{cluster.removeprefix('sha256:')}/namespace/example"


def _task() -> EvaluationTask:
    return EvaluationTask(
        session_id="session",
        task_id="task",
        phase="diagnose",
        objective="Diagnose one namespace.",
        target=TargetRef(kind="kubernetes.namespace", value="example"),
        deadline=datetime(2026, 8, 5, tzinfo=UTC) + timedelta(minutes=5),
        resource_limits=ResourceLimits(
            cpu_seconds=30,
            memory_bytes=134_217_728,
            process_count=8,
            output_bytes=1_048_576,
            wall_clock_seconds=30,
        ),
    )


async def _store() -> InMemoryOntologyInstanceStore:
    catalog = load_ontology_catalog(
        _ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=_ROOT / "rule-catalog/probes",
    )
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    diagnostic = load_diagnostic_catalog_projection(_ROOT)
    await store.replace_subgraph(objects=diagnostic.objects, links=diagnostic.links)
    return store


async def test_projects_live_hold_finding_and_namespace_before_judgment() -> None:
    store = await _store()
    observer = KubernetesOntologyEvidenceObserver(
        store=store,
        clock=lambda: datetime(2026, 8, 5, tzinfo=UTC),
    )
    execution = await DiagnosticFunctionExecutor().derive(
        "kubernetes_missing_dependency_reducer",
        {
            "resources": [
                {
                    "kind": "Deployment",
                    "name": "catalog",
                    "namespace": "example",
                    "desired": 1,
                    "ready": 1,
                    "pod_template": {
                        "projection_complete": True,
                        "containers": [
                            {
                                "name": "catalog",
                                "port_projection_complete": True,
                                "ports": [{"port": 8080}],
                                "env_projection_complete": True,
                                "env": [],
                            }
                        ],
                    },
                },
                {
                    "kind": "Deployment",
                    "name": "frontend",
                    "namespace": "example",
                    "desired": 1,
                    "ready": 1,
                    "pod_template": {
                        "projection_complete": True,
                        "containers": [
                            {
                                "name": "frontend",
                                "port_projection_complete": True,
                                "ports": [],
                                "env_projection_complete": True,
                                "env": [
                                    {
                                        "name": "BACKEND",
                                        "endpoint_host": "catalog",
                                        "endpoint_port": "8080",
                                    }
                                ],
                            }
                        ],
                    },
                },
            ],
            "evidence_complete": True,
        },
    )
    assert len(execution.findings) == 1
    evidence = {
        "observe.kubernetes.dependencies": {
            "status": "available",
            "payload": {
                "cluster": _CLUSTER,
                "evidence_complete": True,
                "findings": list(execution.findings),
                "function_receipts": [execution.receipt],
                "function_inputs": [execution.input_binding],
            },
        }
    }

    await observer.observe(task=_task(), evidence=evidence)
    await observer.observe(task=_task(), evidence=evidence)

    graph = await store.query_objects(
        object_types=("DiagnosticEvidence", "DiagnosticFinding"),
        limit=10,
    )
    assert len(graph.objects) == 2
    assert all(item.revision == 1 for item in graph.objects)
    assert await store.get_object(_namespace_ref()) is not None


async def test_rejects_finding_without_matching_function_receipt() -> None:
    observer = KubernetesOntologyEvidenceObserver(
        store=await _store(),
        clock=lambda: datetime(2026, 8, 5, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="matching ontology function receipt"):
        await observer.observe(
            task=_task(),
            evidence={
                "observe.kubernetes.dependencies": {
                    "status": "available",
                    "payload": {
                        "cluster": _CLUSTER,
                        "evidence_complete": True,
                        "findings": [
                            {
                                "reason": "workload_endpoint_targets_missing_service",
                                "decision": "hold",
                            }
                        ],
                    },
                }
            },
        )


async def test_rejects_findings_changed_after_function_invocation() -> None:
    observer = KubernetesOntologyEvidenceObserver(store=await _store())
    execution = await DiagnosticFunctionExecutor().derive(
        "kubernetes_missing_dependency_reducer",
        {"resources": [], "evidence_complete": True},
    )

    with pytest.raises(ValueError, match="do not match function receipt output"):
        await observer.observe(
            task=_task(),
            evidence={
                "observe.kubernetes.dependencies": {
                    "status": "available",
                    "payload": {
                        "cluster": _CLUSTER,
                        "evidence_complete": True,
                        "findings": [
                            {
                                "reason": "workload_endpoint_targets_missing_service",
                                "decision": "hold",
                            }
                        ],
                        "function_receipts": [execution.receipt],
                        "function_inputs": [execution.input_binding],
                    },
                }
            },
        )


async def test_complete_inventory_removes_stale_namespace_topology_links() -> None:
    store = await _store()
    observer = KubernetesOntologyEvidenceObserver(store=store)
    resources = [
        {
            "kind": "Service",
            "namespace": "example",
            "name": "backend",
            "uid": "service-uid",
            "selector": {"app": "backend"},
        },
        {
            "kind": "Pod",
            "namespace": "example",
            "name": "backend-a",
            "uid": "pod-uid",
            "labels": {"app": "backend"},
        },
    ]

    await observer.observe(
        task=_task(),
        evidence={
            "observe.kubernetes.inventory": {
                "status": "available",
                "payload": {
                    "cluster": _CLUSTER,
                    "evidence_complete": True,
                    "resources": resources,
                    "findings": [],
                },
            }
        },
    )
    changed = [{**resources[0], "selector": {"app": "other"}}, resources[1]]
    await observer.observe(
        task=_task(),
        evidence={
            "observe.kubernetes.inventory": {
                "status": "available",
                "payload": {
                    "cluster": _CLUSTER,
                    "evidence_complete": True,
                    "resources": changed,
                    "findings": [],
                },
            }
        },
    )

    graph = await store.query_objects(object_types=("Resource",), limit=10)
    assert not any(item.link_type == "kubernetes_selects" for item in graph.links)


async def test_complete_inventory_projects_and_replaces_parent_to_child_containment() -> None:
    store = await _store()
    observer = KubernetesOntologyEvidenceObserver(store=store)
    resource = {
        "kind": "Service",
        "namespace": "example",
        "name": "backend",
        "uid": "service-uid",
    }
    payload = {
        "cluster": _CLUSTER,
        "evidence_complete": True,
        "resources": [resource],
        "findings": [],
    }

    await observer.observe(
        task=_task(),
        evidence={
            "observe.kubernetes.inventory": {
                "status": "available",
                "payload": payload,
            }
        },
    )

    resource_id = f"kubernetes.cluster:{_CLUSTER.removeprefix('sha256:')}/resource/service-uid"
    graph = await store.query_objects(object_types=("Resource",), limit=10)
    assert await store.get_object(resource_id) is not None
    assert any(
        item.from_id == _namespace_ref()
        and item.link_type == "contains"
        and item.to_id == resource_id
        for item in graph.links
    )

    await observer.observe(
        task=_task(),
        evidence={
            "observe.kubernetes.inventory": {
                "status": "available",
                "payload": {**payload, "resources": []},
            }
        },
    )

    graph = await store.query_objects(object_types=("Resource",), limit=10)
    assert await store.get_object(resource_id) is None
    assert not any(
        item.link_type == "contains" and item.to_id == resource_id for item in graph.links
    )


async def test_redelivery_uses_receipt_time_not_advancing_observer_clock() -> None:
    store = await _store()
    calls = iter(
        (
            datetime(2026, 8, 5, tzinfo=UTC),
            datetime(2026, 8, 6, tzinfo=UTC),
        )
    )
    observer = KubernetesOntologyEvidenceObserver(store=store, clock=lambda: next(calls))
    execution = await DiagnosticFunctionExecutor().derive(
        "kubernetes_missing_dependency_reducer",
        {
            "resources": [
                {
                    "kind": "Deployment",
                    "name": "catalog",
                    "namespace": "example",
                    "desired": 1,
                    "ready": 1,
                    "pod_template": {
                        "projection_complete": True,
                        "containers": [
                            {
                                "name": "catalog",
                                "port_projection_complete": True,
                                "ports": [{"port": 8080}],
                                "env_projection_complete": True,
                                "env": [],
                            }
                        ],
                    },
                },
                {
                    "kind": "Deployment",
                    "name": "frontend",
                    "namespace": "example",
                    "desired": 1,
                    "ready": 1,
                    "pod_template": {
                        "projection_complete": True,
                        "containers": [
                            {
                                "name": "frontend",
                                "port_projection_complete": True,
                                "ports": [],
                                "env_projection_complete": True,
                                "env": [
                                    {
                                        "name": "BACKEND",
                                        "endpoint_host": "catalog",
                                        "endpoint_port": "8080",
                                    }
                                ],
                            }
                        ],
                    },
                },
            ],
            "evidence_complete": True,
        },
    )
    payload = {
        "cluster": _CLUSTER,
        "evidence_complete": True,
        "findings": list(execution.findings),
        "function_receipts": [execution.receipt],
        "function_inputs": [execution.input_binding],
    }
    evidence = {
        "observe.kubernetes.dependencies": {
            "status": "available",
            "payload": payload,
        }
    }

    await observer.observe(task=_task(), evidence=evidence)
    await observer.observe(task=_task(), evidence=evidence)

    graph = await store.query_objects(
        object_types=("DiagnosticEvidence", "DiagnosticFinding"),
        limit=10,
    )
    assert len(graph.objects) == 2
    assert all(item.revision == 1 for item in graph.objects)


async def test_rejects_unmapped_finding_reason() -> None:
    observer = KubernetesOntologyEvidenceObserver(
        store=await _store(),
        clock=lambda: datetime(2026, 8, 5, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="no ontology mechanism"):
        await observer.observe(
            task=_task(),
            evidence={
                "observe.kubernetes.inventory": {
                    "status": "available",
                    "payload": {
                        "cluster": _CLUSTER,
                        "evidence_complete": True,
                        "findings": [{"reason": "unknown", "decision": "hold"}],
                    },
                }
            },
        )


async def test_rejects_function_inputs_changed_after_invocation() -> None:
    observer = KubernetesOntologyEvidenceObserver(store=await _store())
    execution = await DiagnosticFunctionExecutor().derive(
        "kubernetes_missing_dependency_reducer",
        {"resources": [], "evidence_complete": True},
    )
    changed_binding = {
        **execution.input_binding,
        "arguments": {"resources": [], "evidence_complete": False},
    }

    with pytest.raises(ValueError, match="do not match function receipt input"):
        await observer.observe(
            task=_task(),
            evidence={
                "observe.kubernetes.dependencies": {
                    "status": "available",
                    "payload": {
                        "cluster": _CLUSTER,
                        "evidence_complete": True,
                        "findings": [
                            {
                                "reason": "workload_endpoint_targets_missing_service",
                                "decision": "hold",
                            }
                        ],
                        "function_receipts": [execution.receipt],
                        "function_inputs": [changed_binding],
                    },
                }
            },
        )


async def test_same_namespace_and_uid_remain_isolated_between_clusters() -> None:
    store = await _store()
    observer = KubernetesOntologyEvidenceObserver(store=store)
    resource = {
        "kind": "Service",
        "namespace": "example",
        "name": "backend",
        "uid": "shared-uid",
    }

    for cluster in (_cluster_identity("cluster-a"), _cluster_identity("cluster-b")):
        await observer.observe(
            task=_task(),
            evidence={
                "observe.kubernetes.inventory": {
                    "status": "available",
                    "payload": {
                        "cluster": cluster,
                        "evidence_complete": True,
                        "resources": [resource],
                        "findings": [],
                    },
                }
            },
        )

    assert await store.get_object(_namespace_ref(_cluster_identity("cluster-a"))) is not None
    assert await store.get_object(_namespace_ref(_cluster_identity("cluster-b"))) is not None
    graph = await store.query_objects(
        object_types=("Resource",),
        property_equals={"name": "backend"},
        limit=10,
    )
    assert len(graph.objects) == 2


async def test_uidless_complete_claim_does_not_delete_prior_topology() -> None:
    store = await _store()
    observer = KubernetesOntologyEvidenceObserver(store=store)
    resource = {
        "kind": "Service",
        "namespace": "example",
        "name": "backend",
        "uid": "service-uid",
    }
    base = {
        "status": "available",
        "payload": {
            "cluster": _CLUSTER,
            "evidence_complete": True,
            "resources": [resource],
            "findings": [],
        },
    }

    await observer.observe(
        task=_task(),
        evidence={"observe.kubernetes.inventory": base},
    )
    uidless = {**resource}
    uidless.pop("uid")
    await observer.observe(
        task=_task(),
        evidence={
            "observe.kubernetes.inventory": {
                **base,
                "payload": {**base["payload"], "resources": [uidless]},
            }
        },
    )

    graph = await store.query_objects(
        object_types=("Resource",),
        property_equals={"name": "backend"},
        limit=10,
    )
    assert len(graph.objects) == 1


async def test_incomplete_inventory_withdraws_stale_current_links() -> None:
    store = await _store()
    observer = KubernetesOntologyEvidenceObserver(store=store)
    resources = [
        {
            "kind": "Service",
            "namespace": "example",
            "name": "backend",
            "uid": "service-uid",
            "selector": {"app": "backend"},
        },
        {
            "kind": "Pod",
            "namespace": "example",
            "name": "backend-a",
            "uid": "pod-uid",
            "labels": {"app": "backend"},
        },
    ]
    base_payload = {
        "cluster": _CLUSTER,
        "evidence_complete": True,
        "resources": resources,
        "findings": [],
    }

    await observer.observe(
        task=_task(),
        evidence={
            "observe.kubernetes.inventory": {
                "status": "available",
                "payload": base_payload,
            }
        },
    )
    await observer.observe(
        task=_task(),
        evidence={
            "observe.kubernetes.inventory": {
                "status": "available",
                "payload": {**base_payload, "evidence_complete": False},
            }
        },
    )

    graph = await store.query_objects(object_types=("Resource",), limit=10)
    assert not any(item.link_type == "kubernetes_selects" for item in graph.links)
    assert len([item for item in graph.objects if item.properties.get("name") == "backend"]) == 1
