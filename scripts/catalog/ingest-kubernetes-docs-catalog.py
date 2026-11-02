#!/usr/bin/env python3
"""Ingest a bounded Kubernetes documentation scenario batch.

The source class is Kubernetes official operational documentation, licensed
CC BY 4.0. FDAI stores no copied prose: each curated mapping records only the
public URL, section locator, and review date. Extraction is deterministic and
network-free; a source watcher can later compare the locator upstream without
making catalog generation depend on network availability.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

import yaml
from fdai.core.detection.signals import SignalRole, known_signals

_HERE = pathlib.Path(__file__).resolve()
_REPO_ROOT = next(parent for parent in _HERE.parents if (parent / "pyproject.toml").is_file())
_OUT_DIR = _REPO_ROOT / "rule-catalog" / "chaos-scenarios" / "collected" / "kubernetes-docs"
_SOURCE_PREFIX = "https://kubernetes.io/docs/"
_SOURCE_LICENSE = "CC-BY-4.0"
_REVIEWED_AT = "2026-07-17"
_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_ALLOWED_CATEGORIES = frozenset(
    {
        "compute",
        "network",
        "storage",
        "state",
        "dependency",
        "traffic",
        "time",
        "resource_saturation",
        "identity",
        "quota",
        "cost_governance",
    }
)
_ALLOWED_TARGET_TYPES = frozenset(
    {
        "pod",
        "node",
        "vm",
        "vmss",
        "db",
        "lb",
        "dns",
        "disk",
        "cache",
        "secret_store",
        "identity",
        "ingress",
        "egress",
        "quota",
        "llm_endpoint",
        "control_plane",
    }
)
_ALLOWED_FAULT_FAMILIES = frozenset(
    {
        "stop",
        "delay",
        "drop",
        "corrupt",
        "saturate",
        "throttle",
        "deny",
        "misroute",
        "expire",
        "quota_shrink",
        "oom",
        "hang",
        "preempt",
        "checkpoint_fail",
        "cache_overflow",
        "ramp",
    }
)
_ALLOWED_INTENSITIES = frozenset({"mild", "high", "extreme"})


@dataclass(frozen=True, slots=True)
class Entry:
    slug: str
    source_url: str
    source_section: str
    category: str
    target_type: str
    fault_family: str
    intensity: str
    expected_signal: str
    description: str
    rollback_note: str


_ENTRIES = (
    Entry(
        slug="pod-disruption-budget-gap",
        source_url="https://kubernetes.io/docs/concepts/workloads/pods/disruptions/",
        source_section="pod-disruption-budgets",
        category="compute",
        target_type="pod",
        fault_family="stop",
        intensity="high",
        expected_signal="backend_health",
        description="Concurrent voluntary disruptions exceed the workload availability budget.",
        rollback_note="Restore healthy replicas and stop additional voluntary disruptions.",
    ),
    Entry(
        slug="dns-resolution-failure",
        source_url="https://kubernetes.io/docs/tasks/administer-cluster/dns-debugging-resolution/",
        source_section="check-the-local-dns-configuration-first",
        category="network",
        target_type="dns",
        fault_family="misroute",
        intensity="high",
        expected_signal="request_failure",
        description="Workload DNS configuration prevents service-name resolution.",
        rollback_note="Restore the prior resolver configuration and verify service lookup.",
    ),
    Entry(
        slug="image-pull-backoff",
        source_url="https://kubernetes.io/docs/concepts/containers/images/#imagepullbackoff",
        source_section="imagepullbackoff",
        category="dependency",
        target_type="pod",
        fault_family="deny",
        intensity="high",
        expected_signal="rollout_stall",
        description="A workload cannot pull its declared image and the rollout stalls.",
        rollback_note="Restore the previous resolvable image reference and restart the rollout.",
    ),
    Entry(
        slug="crash-loop-backoff-liveness-probe",
        source_url=(
            "https://kubernetes.io/docs/tasks/configure-pod-container/"
            "configure-liveness-readiness-startup-probes/"
        ),
        source_section="define-a-liveness-command",
        category="compute",
        target_type="pod",
        fault_family="stop",
        intensity="high",
        expected_signal="pod_crash_loop_back_off",
        description=(
            "Misconfigured or failing livenessProbe repeatedly restarts the container "
            "into CrashLoopBackOff."
        ),
        rollback_note="Restore valid livenessProbe command or threshold parameters and redeploy.",
    ),
    Entry(
        slug="readiness-probe-endpoint-removal",
        source_url=(
            "https://kubernetes.io/docs/tasks/configure-pod-container/"
            "configure-liveness-readiness-startup-probes/"
        ),
        source_section="define-readiness-probes",
        category="traffic",
        target_type="pod",
        fault_family="deny",
        intensity="mild",
        expected_signal="pod_unready",
        description=(
            "Failing readinessProbe removes the Pod from Service EndpointSlices "
            "without restarting the container."
        ),
        rollback_note="Restore backend dependency health or readinessProbe port configuration.",
    ),
    Entry(
        slug="container-oom-killed-memory-limit",
        source_url="https://kubernetes.io/docs/tasks/configure-pod-container/assign-memory-resource/",
        source_section="exceed-a-container-s-memory-limit",
        category="resource_saturation",
        target_type="pod",
        fault_family="oom",
        intensity="high",
        expected_signal="pod_oom_killed",
        description=(
            "Container memory usage exceeds its cgroup limit and triggers "
            "kernel OOMKilled termination."
        ),
        rollback_note=(
            "Restore safe memory limit and request sizing or roll back "
            "the leaking workload revision."
        ),
    ),
    Entry(
        slug="kubelet-node-not-ready-stop",
        source_url="https://kubernetes.io/docs/concepts/architecture/nodes/",
        source_section="node-status",
        category="compute",
        target_type="node",
        fault_family="stop",
        intensity="high",
        expected_signal="resource_availability",
        description=(
            "Stopped kubelet agent causes NodeReady status to become Unknown "
            "and triggers pod eviction."
        ),
        rollback_note="Restart the node kubelet service and verify NodeReady status recovery.",
    ),
    Entry(
        slug="network-policy-egress-deny-drop",
        source_url="https://kubernetes.io/docs/concepts/services-networking/network-policies/",
        source_section="default-deny-all-egress-traffic",
        category="network",
        target_type="egress",
        fault_family="drop",
        intensity="high",
        expected_signal="request_failure",
        description=(
            "Restrictive egress NetworkPolicy drops outbound Pod traffic "
            "despite destination ingress allowance."
        ),
        rollback_note=(
            "Restore the egress NetworkPolicy allow rule for the target service selector and port."
        ),
    ),
    Entry(
        slug="service-selector-label-mismatch",
        source_url="https://kubernetes.io/docs/concepts/services-networking/service/",
        source_section="defining-a-service",
        category="network",
        target_type="lb",
        fault_family="misroute",
        intensity="high",
        expected_signal="backend_health",
        description=(
            "Service label selector mismatch leaves EndpointSlices empty "
            "and collapses backend health."
        ),
        rollback_note="Align the Service selector labels with the active Pod template labels.",
    ),
    Entry(
        slug="resource-quota-admission-denial",
        source_url="https://kubernetes.io/docs/concepts/policy/resource-quotas/",
        source_section="compute-resource-quota",
        category="quota",
        target_type="quota",
        fault_family="quota_shrink",
        intensity="mild",
        expected_signal="rollout_stall",
        description=(
            "Namespace ResourceQuota exhaustion blocks ReplicaSet Pod creation during rollout."
        ),
        rollback_note="Restore namespace ResourceQuota headroom or right-size workload requests.",
    ),
    Entry(
        slug="node-taint-untolerated-pending",
        source_url="https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/",
        source_section="concepts",
        category="compute",
        target_type="node",
        fault_family="deny",
        intensity="mild",
        expected_signal="rollout_stall",
        description=(
            "Untolerated NoSchedule or NoExecute node taints leave newly "
            "scheduled Pods in Pending state."
        ),
        rollback_note=(
            "Remove the unintended node taint or add the matching toleration to the workload spec."
        ),
    ),
    Entry(
        slug="pvc-provisioning-mount-stall",
        source_url="https://kubernetes.io/docs/concepts/storage/persistent-volumes/",
        source_section="lifecycle-of-a-volume-and-claim",
        category="storage",
        target_type="disk",
        fault_family="hang",
        intensity="high",
        expected_signal="pod_unready",
        description=(
            "Unbound PersistentVolumeClaim or cross-zone volume attach failure stalls Pod startup."
        ),
        rollback_note=(
            "Restore StorageClass availability or attach a zone-aligned PersistentVolume."
        ),
    ),
    Entry(
        slug="ingress-backend-gateway-timeout",
        source_url="https://kubernetes.io/docs/concepts/services-networking/ingress/",
        source_section="the-ingress-resource",
        category="traffic",
        target_type="ingress",
        fault_family="delay",
        intensity="high",
        expected_signal="gateway_latency",
        description=(
            "Slow upstream Pod response across Ingress routing rules elevates "
            "gateway first-byte latency."
        ),
        rollback_note=(
            "Restore upstream service response latency or roll back the Ingress backend route."
        ),
    ),
    Entry(
        slug="configmap-drift-rollout-regression",
        source_url="https://kubernetes.io/docs/concepts/configuration/configmap/",
        source_section="using-configmaps",
        category="state",
        target_type="pod",
        fault_family="corrupt",
        intensity="mild",
        expected_signal="config_drift",
        description=(
            "Out-of-band ConfigMap mutation introduces runtime configuration drift "
            "from declared manifests."
        ),
        rollback_note=(
            "Reconcile the ConfigMap with the declared GitOps revision and restart affected Pods."
        ),
    ),
    Entry(
        slug="container-abnormal-exit-entrypoint",
        source_url=(
            "https://kubernetes.io/docs/tasks/debug/debug-application/determine-reason-pod-failure/"
        ),
        source_section="writing-and-reading-a-termination-message",
        category="compute",
        target_type="pod",
        fault_family="stop",
        intensity="high",
        expected_signal="pod_abnormal_termination",
        description=(
            "Invalid container entrypoint or command causes immediate non-zero exit "
            "upon container start."
        ),
        rollback_note="Restore the verified container command and arguments in the Pod template.",
    ),
    Entry(
        slug="init-container-startup-failure",
        source_url="https://kubernetes.io/docs/concepts/workloads/pods/init-containers/",
        source_section="understanding-init-containers",
        category="dependency",
        target_type="pod",
        fault_family="stop",
        intensity="high",
        expected_signal="rollout_stall",
        description=(
            "Failing InitContainer blocks main application container startup "
            "and stalls deployment rollout."
        ),
        rollback_note=(
            "Restore the prerequisite dependency or InitContainer command and restart the rollout."
        ),
    ),
    Entry(
        slug="startup-probe-premature-restart",
        source_url=(
            "https://kubernetes.io/docs/tasks/configure-pod-container/"
            "configure-liveness-readiness-startup-probes/"
        ),
        source_section="define-startup-probes",
        category="compute",
        target_type="pod",
        fault_family="stop",
        intensity="high",
        expected_signal="pod_probe_failure",
        description=(
            "Missing or overly short startupProbe causes livenessProbe to kill "
            "slow-starting containers before initialization finishes."
        ),
        rollback_note=(
            "Configure a startupProbe failureThreshold and periodSeconds "
            "covering worst-case initialization time."
        ),
    ),
    Entry(
        slug="ephemeral-storage-eviction",
        source_url=(
            "https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/"
        ),
        source_section="local-ephemeral-storage",
        category="storage",
        target_type="pod",
        fault_family="saturate",
        intensity="high",
        expected_signal="pod_failed",
        description=(
            "Container rootfs logs or emptyDir usage exceeds ephemeral-storage "
            "limits and triggers kubelet Pod eviction."
        ),
        rollback_note=(
            "Rotate or redirect container logs and raise ephemeral-storage "
            "limits or attach persistent storage."
        ),
    ),
    Entry(
        slug="cpu-cfs-quota-throttling-latency",
        source_url=(
            "https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/"
        ),
        source_section="how-pods-with-resource-limits-are-run",
        category="resource_saturation",
        target_type="pod",
        fault_family="throttle",
        intensity="high",
        expected_signal="gateway_latency",
        description=(
            "Restrictive container CPU limit triggers Linux CFS bandwidth "
            "throttling and elevates tail request latency."
        ),
        rollback_note="Raise the container CPU limit or right-size worker thread concurrency.",
    ),
    Entry(
        slug="topology-spread-skew-hotspot",
        source_url=(
            "https://kubernetes.io/docs/concepts/scheduling-eviction/topology-spread-constraints/"
        ),
        source_section="spread-constraint-definition",
        category="compute",
        target_type="node",
        fault_family="saturate",
        intensity="mild",
        expected_signal="node_cpu",
        description=(
            "Missing topologySpreadConstraints concentrates replicas onto a "
            "single zone or node under traffic load."
        ),
        rollback_note=(
            "Apply zone and hostname topologySpreadConstraints and rebalance Deployment replicas."
        ),
    ),
    Entry(
        slug="priority-class-preemption-cascade",
        source_url=(
            "https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/"
        ),
        source_section="preemption",
        category="compute",
        target_type="pod",
        fault_family="preempt",
        intensity="high",
        expected_signal="pod_restart",
        description=(
            "High-PriorityClass workload surge preempts lower-priority worker "
            "Pods across constrained nodes."
        ),
        rollback_note=(
            "Restore node pool capacity headroom or bound PriorityClass resource quotas."
        ),
    ),
    Entry(
        slug="hpa-metrics-api-unavailable",
        source_url="https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/",
        source_section="how-does-a-horizontalpodautoscaler-work",
        category="compute",
        target_type="pod",
        fault_family="saturate",
        intensity="high",
        expected_signal="node_cpu",
        description=(
            "Unavailable metrics-server or missing Pod CPU requests prevent "
            "HorizontalPodAutoscaler scale-out during traffic spikes."
        ),
        rollback_note=(
            "Restore metrics-server availability and ensure Pod CPU requests are declared."
        ),
    ),
    Entry(
        slug="external-traffic-policy-local-blackhole",
        source_url=(
            "https://kubernetes.io/docs/tasks/access-application-cluster/"
            "create-external-load-balancer/"
        ),
        source_section="preserving-the-client-source-ip",
        category="network",
        target_type="lb",
        fault_family="misroute",
        intensity="high",
        expected_signal="backend_health",
        description=(
            "Service with externalTrafficPolicy Local drops health probes on "
            "nodes without local Pod endpoints."
        ),
        rollback_note=(
            "Ensure Pod placement covers target nodes or switch Service "
            "externalTrafficPolicy to Cluster."
        ),
    ),
    Entry(
        slug="prestop-hook-grace-period-drop",
        source_url="https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/",
        source_section="pod-termination",
        category="traffic",
        target_type="pod",
        fault_family="drop",
        intensity="mild",
        expected_signal="request_failure",
        description=(
            "Pod terminates without a preStop drain delay before Service "
            "endpoint removal propagates, dropping in-flight requests."
        ),
        rollback_note=(
            "Add a preStop sleep hook and align terminationGracePeriodSeconds "
            "with load-balancer drain timing."
        ),
    ),
    Entry(
        slug="secret-volume-mount-missing-stall",
        source_url="https://kubernetes.io/docs/concepts/configuration/secret/",
        source_section="using-secrets-as-files-from-a-pod",
        category="dependency",
        target_type="secret_store",
        fault_family="deny",
        intensity="high",
        expected_signal="pod_unready",
        description=(
            "Missing referenced Kubernetes Secret or Key Vault CSI mount "
            "blocks Pod container creation."
        ),
        rollback_note=(
            "Restore the required Secret object or Key Vault CSI identity "
            "permission in the target namespace."
        ),
    ),
    Entry(
        slug="coredns-upstream-forward-timeout",
        source_url="https://kubernetes.io/docs/tasks/administer-cluster/dns-debugging-resolution/",
        source_section="known-issues",
        category="network",
        target_type="dns",
        fault_family="delay",
        intensity="high",
        expected_signal="gateway_latency",
        description=(
            "Unreachable upstream DNS forwarder causes CoreDNS lookup timeouts across Pods."
        ),
        rollback_note="Restore upstream DNS forwarder reachability in the CoreDNS ConfigMap.",
    ),
    Entry(
        slug="endpointslice-stale-terminating-ready",
        source_url="https://kubernetes.io/docs/concepts/services-networking/endpoint-slices/",
        source_section="terminating",
        category="traffic",
        target_type="lb",
        fault_family="misroute",
        intensity="high",
        expected_signal="request_failure",
        description=(
            "Stale terminating EndpointSlice entries continue receiving new Service requests."
        ),
        rollback_note="Reconcile EndpointSlice controller state and drain terminating Pods.",
    ),
    Entry(
        slug="apiserver-admission-webhook-timeout",
        source_url=(
            "https://kubernetes.io/docs/reference/access-authn-authz/"
            "extensible-admission-controllers/"
        ),
        source_section="failure-policy",
        category="dependency",
        target_type="control_plane",
        fault_family="deny",
        intensity="high",
        expected_signal="rollout_stall",
        description="Unavailable admission webhook with failurePolicy Fail blocks Pod creation.",
        rollback_note="Restore webhook service availability or relax the webhook failurePolicy.",
    ),
    Entry(
        slug="etcd-quorum-leader-election-stall",
        source_url="https://kubernetes.io/docs/tasks/administer-cluster/configure-upgrade-etcd/",
        source_section="backing-up-an-etcd-cluster",
        category="state",
        target_type="control_plane",
        fault_family="hang",
        intensity="extreme",
        expected_signal="resource_availability",
        description="Etcd disk latency or member loss triggers leader re-election and API stalls.",
        rollback_note="Restore etcd quorum membership and dedicated low-latency storage IOPS.",
    ),
    Entry(
        slug="kube-proxy-iptables-sync-lag",
        source_url="https://kubernetes.io/docs/reference/command-line-tools-reference/kube-proxy/",
        source_section="options",
        category="network",
        target_type="node",
        fault_family="delay",
        intensity="mild",
        expected_signal="gateway_latency",
        description=(
            "Delayed kube-proxy iptables synchronization leaves stale Service rules on nodes."
        ),
        rollback_note="Restart unhealthy kube-proxy Pod or switch to IPVS dataplane mode.",
    ),
    Entry(
        slug="cronjob-concurrency-forbid-stall",
        source_url="https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/",
        source_section="concurrency-policy",
        category="compute",
        target_type="pod",
        fault_family="hang",
        intensity="mild",
        expected_signal="rollout_stall",
        description=(
            "Hung Job run under concurrencyPolicy Forbid blocks subsequent CronJob schedules."
        ),
        rollback_note="Set activeDeadlineSeconds on the Job spec and terminate the hung Job Pod.",
    ),
    Entry(
        slug="daemonset-node-taint-eviction-gap",
        source_url="https://kubernetes.io/docs/concepts/workloads/controllers/daemonset/",
        source_section="how-daemon-pods-are-scheduled",
        category="compute",
        target_type="node",
        fault_family="deny",
        intensity="high",
        expected_signal="pod_unready",
        description=(
            "Missing taint toleration on a critical DaemonSet leaves tainted nodes unmonitored."
        ),
        rollback_note=(
            "Add the required NoSchedule and NoExecute tolerations to the DaemonSet spec."
        ),
    ),
    Entry(
        slug="statefulset-ordinal-pod-stuck-terminating",
        source_url="https://kubernetes.io/docs/tasks/run-application/force-delete-stateful-set-pod/",
        source_section="statefulset-considerations",
        category="state",
        target_type="pod",
        fault_family="hang",
        intensity="high",
        expected_signal="rollout_stall",
        description=(
            "Unresponsive node leaves a StatefulSet Pod stuck Terminating and blocks rollout."
        ),
        rollback_note="Recover the worker node kubelet or safely fence and delete the stuck Pod.",
    ),
    Entry(
        slug="job-backoff-limit-exceeded-failure",
        source_url="https://kubernetes.io/docs/concepts/workloads/controllers/job/",
        source_section="pod-backoff-failure-policy",
        category="compute",
        target_type="pod",
        fault_family="stop",
        intensity="high",
        expected_signal="pod_failed",
        description=(
            "Repeated batch container failures exhaust Job backoffLimit and mark Job Failed."
        ),
        rollback_note="Fix the batch input or transient dependency and re-create the Job.",
    ),
    Entry(
        slug="replicaset-selector-adoption-conflict",
        source_url="https://kubernetes.io/docs/concepts/workloads/controllers/replicaset/",
        source_section="working-with-replicasets",
        category="state",
        target_type="pod",
        fault_family="corrupt",
        intensity="mild",
        expected_signal="config_drift",
        description=(
            "Overlapping Pod label selectors across controllers cause ReplicaSet contention."
        ),
        rollback_note="Assign unique template labels to each Deployment and ReplicaSet selector.",
    ),
    Entry(
        slug="node-disk-pressure-taint-eviction",
        source_url="https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/",
        source_section="disk-pressure",
        category="storage",
        target_type="node",
        fault_family="saturate",
        intensity="high",
        expected_signal="pod_restart",
        description="Node DiskPressure condition taints the node and evicts running Pods.",
        rollback_note="Prune unused container images and logs or expand the node OS/data volume.",
    ),
    Entry(
        slug="node-memory-pressure-qos-eviction",
        source_url="https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/",
        source_section="memory-pressure",
        category="resource_saturation",
        target_type="node",
        fault_family="oom",
        intensity="high",
        expected_signal="host_memory",
        description="Node MemoryPressure condition evicts BestEffort and Burstable Pods.",
        rollback_note="Right-size Pod memory limits and scale out the AKS node pool.",
    ),
    Entry(
        slug="node-pid-pressure-fork-denial",
        source_url="https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/",
        source_section="pid-pressure",
        category="resource_saturation",
        target_type="node",
        fault_family="saturate",
        intensity="high",
        expected_signal="pod_abnormal_termination",
        description="Node PIDPressure exhausts process IDs and prevents new process forks in Pods.",
        rollback_note="Enforce Pod pidsLimit and terminate leaking or zombie-spawning containers.",
    ),
    Entry(
        slug="kubelet-pleg-unhealthy-node-not-ready",
        source_url="https://kubernetes.io/docs/concepts/architecture/nodes/",
        source_section="condition",
        category="compute",
        target_type="node",
        fault_family="hang",
        intensity="high",
        expected_signal="resource_availability",
        description=(
            "Container runtime relist stall triggers PLEG unhealthy and NodeNotReady state."
        ),
        rollback_note="Restart containerd and kubelet on the affected worker node.",
    ),
    Entry(
        slug="container-runtime-image-gc-stall",
        source_url="https://kubernetes.io/docs/concepts/architecture/garbage-collection/",
        source_section="containers-images",
        category="storage",
        target_type="node",
        fault_family="saturate",
        intensity="mild",
        expected_signal="rollout_stall",
        description=(
            "Failed kubelet image garbage collection leaves node imagefs full during rollout."
        ),
        rollback_note="Clear unreferenced container images and verify imageGCHighThresholdPercent.",
    ),
    Entry(
        slug="ingress-class-controller-mismatch",
        source_url="https://kubernetes.io/docs/concepts/services-networking/ingress/",
        source_section="ingress-class",
        category="network",
        target_type="ingress",
        fault_family="misroute",
        intensity="high",
        expected_signal="backend_health",
        description="Unmatched ingressClassName leaves Ingress rules unreconciled with no address.",
        rollback_note="Set ingressClassName to the active Ingress controller class.",
    ),
    Entry(
        slug="network-policy-ingress-isolated-drop",
        source_url="https://kubernetes.io/docs/concepts/services-networking/network-policies/",
        source_section="default-deny-all-ingress-traffic",
        category="network",
        target_type="ingress",
        fault_family="drop",
        intensity="high",
        expected_signal="request_failure",
        description="Default-deny ingress NetworkPolicy blocks health probes and upstream callers.",
        rollback_note=(
            "Add an ingress NetworkPolicy rule allowing the gateway and probe namespaces."
        ),
    ),
    Entry(
        slug="service-session-affinity-clientip-skew",
        source_url="https://kubernetes.io/docs/reference/networking/virtual-ips/",
        source_section="session-affinity",
        category="traffic",
        target_type="lb",
        fault_family="saturate",
        intensity="mild",
        expected_signal="node_cpu",
        description="ClientIP sessionAffinity behind a NAT proxy routes all traffic to one Pod.",
        rollback_note="Switch session affinity to application-layer cookies or disable ClientIP.",
    ),
    Entry(
        slug="dns-ndots-search-path-amplification",
        source_url="https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/",
        source_section="pod-dns-config",
        category="network",
        target_type="dns",
        fault_family="throttle",
        intensity="mild",
        expected_signal="gateway_latency",
        description="Default ndots 5 search-domain expansion multiplies external DNS queries.",
        rollback_note="Configure dnsConfig ndots 2 or use fully qualified domain names.",
    ),
    Entry(
        slug="dual-stack-ipv6-route-blackhole",
        source_url="https://kubernetes.io/docs/concepts/services-networking/dual-stack/",
        source_section="configure-ipv4-ipv6-dual-stack",
        category="network",
        target_type="egress",
        fault_family="drop",
        intensity="high",
        expected_signal="request_failure",
        description=(
            "Misconfigured IPv6 egress route in a dual-stack cluster blackholes AAAA traffic."
        ),
        rollback_note="Restore IPv6 subnet routing or set PreferDualStack to single-stack IPv4.",
    ),
    Entry(
        slug="volume-subpath-configmap-stale-mount",
        source_url="https://kubernetes.io/docs/concepts/storage/volumes/",
        source_section="using-subpath",
        category="state",
        target_type="pod",
        fault_family="corrupt",
        intensity="mild",
        expected_signal="config_drift",
        description="ConfigMap mounted via subPath prevents automatic kubelet file updates.",
        rollback_note="Mount the ConfigMap directory without subPath or trigger a rolling restart.",
    ),
    Entry(
        slug="volume-fsgroup-permission-denied",
        source_url="https://kubernetes.io/docs/tasks/configure-pod-container/security-context/",
        source_section="configure-volume-permission-and-ownership-change-policy-for-pods",
        category="storage",
        target_type="disk",
        fault_family="deny",
        intensity="high",
        expected_signal="pod_crash_loop_back_off",
        description=(
            "Missing Pod securityContext fsGroup prevents non-root container volume writes."
        ),
        rollback_note="Set securityContext fsGroup matching the non-root container group ID.",
    ),
    Entry(
        slug="csi-volume-multi-attach-conflict",
        source_url="https://kubernetes.io/docs/concepts/storage/persistent-volumes/",
        source_section="access-modes",
        category="storage",
        target_type="disk",
        fault_family="deny",
        intensity="high",
        expected_signal="pod_unready",
        description="ReadWriteOnce disk remains attached to a prior node and blocks new Pod mount.",
        rollback_note=(
            "Detach the stale VolumeAttachment or use ReadWriteMany shared file storage."
        ),
    ),
    Entry(
        slug="emptydir-memory-tmpfs-limit-oom",
        source_url="https://kubernetes.io/docs/concepts/storage/volumes/",
        source_section="emptydir",
        category="resource_saturation",
        target_type="pod",
        fault_family="oom",
        intensity="high",
        expected_signal="pod_oom_killed",
        description=(
            "Unbounded memory-backed emptyDir tmpfs writes count against Pod memory limit."
        ),
        rollback_note="Declare emptyDir sizeLimit or switch medium from Memory to disk storage.",
    ),
    Entry(
        slug="limitrange-default-request-admission-reject",
        source_url="https://kubernetes.io/docs/concepts/policy/limit-range/",
        source_section="constraints-on-resource-limits-and-requests",
        category="quota",
        target_type="quota",
        fault_family="quota_shrink",
        intensity="mild",
        expected_signal="rollout_stall",
        description=(
            "Namespace LimitRange max constraint rejects Pods requesting higher CPU or RAM."
        ),
        rollback_note="Align workload resource requests with the namespace LimitRange bounds.",
    ),
)


def _validate_entry(entry: Entry) -> None:
    if not _SLUG_PATTERN.fullmatch(entry.slug):
        raise ValueError("invalid_slug")
    if not entry.source_url.startswith(_SOURCE_PREFIX):
        raise ValueError("unsupported_source_url")
    if not entry.source_section.strip():
        raise ValueError("missing_source_section")
    if entry.category not in _ALLOWED_CATEGORIES:
        raise ValueError("unsupported_category")
    if entry.target_type not in _ALLOWED_TARGET_TYPES:
        raise ValueError("unsupported_target_type")
    if entry.fault_family not in _ALLOWED_FAULT_FAMILIES:
        raise ValueError("unsupported_fault_family")
    if entry.intensity not in _ALLOWED_INTENSITIES:
        raise ValueError("unsupported_intensity")
    if not entry.description.strip() or not entry.rollback_note.strip():
        raise ValueError("missing_description_or_rollback_note")
    signal = known_signals().get(entry.expected_signal)
    if signal is None:
        raise ValueError("unknown_expected_signal")
    if signal.role is SignalRole.RCA_ONLY:
        raise ValueError("rca_only_signal_not_scenario_eligible")


def _to_body(entry: Entry) -> dict[str, object]:
    _validate_entry(entry)
    return {
        "id": f"chaos.kubernetes-docs.{entry.slug}",
        "version": 1,
        "provenance": {
            "source": "vendor-doc",
            "source_url": entry.source_url,
            "source_ref": (
                f"section={entry.source_section};license={_SOURCE_LICENSE};reviewed={_REVIEWED_AT}"
            ),
            "synthesis_method": "manual",
        },
        "category": entry.category,
        "target_type": entry.target_type,
        "fault_family": entry.fault_family,
        "intensity": entry.intensity,
        "duration_seconds": 360,
        "expected_signal": entry.expected_signal,
        "injector": "needs-injector",
        "blast_radius_cap": 1,
        "rollback_note": entry.rollback_note,
        "gates": {"shadow_status": "pending", "enforce_status": None},
        "requires_hardware": False,
        "description": entry.description,
        "tags": ["kubernetes", "vendor-doc"],
    }


def main() -> int:
    slugs = [entry.slug for entry in _ENTRIES]
    if len(slugs) != len(set(slugs)):
        raise ValueError("duplicate_slug")
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    valid_names = {f"{entry.slug}.yaml" for entry in _ENTRIES}
    for existing in _OUT_DIR.glob("*.yaml"):
        if existing.name not in valid_names:
            existing.unlink()
    for entry in _ENTRIES:
        path = _OUT_DIR / f"{entry.slug}.yaml"
        path.write_text(yaml.safe_dump(_to_body(entry), sort_keys=False))
    print(f"wrote {len(_ENTRIES)} Kubernetes docs scenarios -> {_OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
