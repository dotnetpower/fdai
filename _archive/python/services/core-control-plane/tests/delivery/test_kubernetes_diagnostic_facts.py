"""Kubernetes diagnostic fact extraction tests."""

from __future__ import annotations

import pytest
from fdai.delivery.kubernetes_diagnostic_facts import diagnostic_properties


def test_collects_node_pressure_and_transition_times_without_messages() -> None:
    props = diagnostic_properties(
        resource_type="kubernetes.node",
        spec=None,
        status={
            "conditions": [
                {
                    "type": "MemoryPressure",
                    "status": "True",
                    "reason": "KubeletHasInsufficientMemory",
                    "message": "provider-controlled text",
                    "lastTransitionTime": "2026-09-10T00:00:00Z",
                },
                {"type": "Ready", "status": "False", "reason": "KubeletNotReady"},
            ]
        },
    )

    assert props["diagnostic_conditions"] == (
        {
            "type": "MemoryPressure",
            "status": "True",
            "reason": "KubeletHasInsufficientMemory",
            "last_transition_time": "2026-09-10T00:00:00+00:00",
        },
        {"type": "Ready", "status": "False", "reason": "KubeletNotReady"},
    )
    assert "message" not in str(props)


def test_collects_pod_scheduling_resources_probes_and_container_groups() -> None:
    props = diagnostic_properties(
        resource_type="kubernetes.pod",
        spec={
            "priorityClassName": "system-cluster-critical",
            "restartPolicy": "Always",
            "schedulerName": "default-scheduler",
            "serviceAccountName": "workload",
            "nodeSelector": {"kubernetes.io/os": "linux"},
            "tolerations": [{"key": "critical", "operator": "Exists", "effect": "NoSchedule"}],
            "affinity": {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {}}},
            "containers": [
                {
                    "name": "api",
                    "livenessProbe": {"httpGet": {"path": "/health"}},
                    "readinessProbe": {"httpGet": {"path": "/ready"}},
                    "resources": {
                        "requests": {"cpu": "250m", "memory": "128Mi"},
                        "limits": {"cpu": "1", "memory": "512Mi"},
                    },
                }
            ],
            "volumes": [{"persistentVolumeClaim": {"claimName": "data"}}],
        },
        status={
            "qosClass": "Burstable",
            "conditions": [
                {
                    "type": "PodScheduled",
                    "status": "False",
                    "reason": "Unschedulable",
                    "lastTransitionTime": "2026-09-10T00:00:00Z",
                }
            ],
            "initContainerStatuses": [
                {
                    "name": "migrate",
                    "ready": False,
                    "restartCount": 2,
                    "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                }
            ],
        },
    )

    assert props["qos_class"] == "Burstable"
    assert props["pvc_claim_names"] == ("data",)
    assert props["probe_kinds"] == (
        {"container_name": "api", "probe_kind": "liveness"},
        {"container_name": "api", "probe_kind": "readiness"},
    )
    assert props["container_resources"] == (
        {
            "container_name": "api",
            "limits": {"cpu": "1", "memory": "512Mi"},
            "requests": {"cpu": "250m", "memory": "128Mi"},
        },
    )
    assert props["init_container_restart_count"] == 2
    assert props["init_container_waiting_reasons"] == ("CrashLoopBackOff",)


def test_rejects_duplicate_condition_types() -> None:
    with pytest.raises(ValueError, match="condition type is duplicated"):
        diagnostic_properties(
            resource_type="kubernetes.node",
            spec=None,
            status={
                "conditions": [
                    {"type": "Ready", "status": "True"},
                    {"type": "Ready", "status": "False"},
                ]
            },
        )


def test_collects_workload_specific_status_counts() -> None:
    props = diagnostic_properties(
        resource_type="kubernetes.daemon-set",
        spec={},
        status={
            "desiredNumberScheduled": 3,
            "numberReady": 2,
            "numberUnavailable": 1,
        },
    )

    assert props["status_counts"] == {
        "desired_number_scheduled": 3,
        "number_ready": 2,
        "number_unavailable": 1,
    }


def test_collects_storage_binding_without_provider_details() -> None:
    pvc = diagnostic_properties(
        resource_type="kubernetes.persistent-volume-claim",
        spec={
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": "10Gi"}},
            "storageClassName": "managed-csi",
            "volumeMode": "Filesystem",
            "volumeName": "pv-data",
        },
        status={"phase": "Bound", "capacity": {"storage": "10Gi"}},
    )
    pv = diagnostic_properties(
        resource_type="kubernetes.persistent-volume",
        spec={
            "capacity": {"storage": "10Gi"},
            "claimRef": {"name": "data", "namespace": "default", "uid": "uid-pvc"},
            "persistentVolumeReclaimPolicy": "Delete",
            "storageClassName": "managed-csi",
        },
        status={"phase": "Bound", "message": "provider-controlled"},
    )

    assert pvc["volume_name"] == "pv-data"
    assert pvc["requested_storage"] == "10Gi"
    assert pv["claim_uid"] == "uid-pvc"
    assert "message" not in str(pv)


def test_collects_policy_autoscale_quota_and_limit_summaries() -> None:
    hpa = diagnostic_properties(
        resource_type="kubernetes.horizontal-pod-autoscaler",
        spec={
            "scaleTargetRef": {"apiVersion": "apps/v1", "kind": "Deployment", "name": "api"},
            "minReplicas": 2,
            "maxReplicas": 10,
        },
        status={"currentReplicas": 2, "desiredReplicas": 4},
    )
    pdb = diagnostic_properties(
        resource_type="kubernetes.pod-disruption-budget",
        spec={"selector": {"matchLabels": {"app": "api"}}, "minAvailable": "50%"},
        status={"currentHealthy": 2, "desiredHealthy": 2, "disruptionsAllowed": 0},
    )
    policy = diagnostic_properties(
        resource_type="kubernetes.network-policy",
        spec={
            "podSelector": {"matchLabels": {"app": "api"}},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [{}],
            "egress": [{}, {}],
        },
        status=None,
    )
    quota = diagnostic_properties(
        resource_type="kubernetes.resource-quota",
        spec={},
        status={"hard": {"requests.cpu": "4"}, "used": {"requests.cpu": "3"}},
    )
    limits = diagnostic_properties(
        resource_type="kubernetes.limit-range",
        spec={"limits": [{"type": "Container", "default": {"cpu": "1"}}]},
        status=None,
    )

    assert hpa["scale_target_name"] == "api"
    assert hpa["desired_replicas"] == 4
    assert pdb["selector"] == {"app": "api"}
    assert pdb["disruptions_allowed"] == 0
    assert policy["policy_types"] == ("Egress", "Ingress")
    assert policy["egress_rule_count"] == 2
    assert quota["quota_used"] == {"requests.cpu": "3"}
    assert limits["limit_summaries"] == ({"type": "Container", "default": {"cpu": "1"}},)


def test_preserves_network_policy_match_all_selector() -> None:
    policy = diagnostic_properties(
        resource_type="kubernetes.network-policy",
        spec={"podSelector": {}, "policyTypes": ["Ingress"]},
        status=None,
    )

    assert policy["selector"] == {}
    assert policy["selector_matches_all"] is True


def test_collects_endpoint_slice_health_without_addresses() -> None:
    props = diagnostic_properties(
        resource_type="kubernetes.endpoint-slice",
        spec=None,
        status=None,
        body={
            "addressType": "IPv4",
            "ports": [{"name": "http", "port": 80}],
            "endpoints": [
                {
                    "addresses": ["10.0.0.4"],
                    "conditions": {"ready": True, "serving": True, "terminating": False},
                    "targetRef": {"kind": "Pod", "uid": "uid-ready"},
                },
                {
                    "addresses": ["10.0.0.5"],
                    "conditions": {"ready": False},
                    "targetRef": {"kind": "Pod", "uid": "uid-unready"},
                },
            ],
        },
    )

    assert props["endpoint_count"] == 2
    assert props["ready"] == 1
    assert props["serving"] == 1
    assert props["serving_unknown"] == 1
    assert props["target_uids"] == ("uid-ready", "uid-unready")
    assert "10.0.0" not in str(props)
