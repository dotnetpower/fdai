"""Ingest AWS Fault Injection Simulator scenario library.

AWS FIS ships ~40 pre-authored scenarios across EC2, ECS, EKS, RDS,
Aurora, S3, SSM, DynamoDB, IAM, and CloudWatch. This ingester
projects them into the FDAI catalog as CSP-neutral entries so the
symptom index and RCA can reason about them alongside Azure faults.

FDAI's implementation focus is Azure (see
`.github/copilot-instructions.md` "Implementation Focus"); AWS is
TBD. Every entry here therefore ships with
`injector: cross-csp-reference` - the catalog knows about the fault
for symptom vocabulary and T2 RCA candidate matching, but the factory
reports it as non-executable so nothing tries to inject an AWS fault
from our Azure-only stack. `needs-injector` is reserved for scenarios
whose CSP FDAI targets but whose delivery adapter has not landed;
cross-csp-reference makes the semantic distinction honest.

Source: AWS FIS documentation. Hand-curated CSP-neutral projection;
the upstream `actionId` is preserved in `provenance.source_ref` so an
operator can cross-reference.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

import yaml
from fdai.core.detection.signals import SignalRole, known_signals

_HERE = pathlib.Path(__file__).resolve()
_REPO_ROOT = next(parent for parent in _HERE.parents if (parent / "pyproject.toml").is_file())
_OUT_DIR = _REPO_ROOT / "rule-catalog" / "chaos-scenarios" / "collected" / "aws-fis"
_ALERT_WINDOW_S = 360.0
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
    action_id: str  # AWS FIS actionId
    description: str
    category: str
    target_type: str
    fault_family: str
    intensity: str
    expected_signal: str
    params: dict[str, str]
    rollback_note: str
    blast_radius_cap: int = 1


_ENTRIES: tuple[Entry, ...] = (
    # -- EC2 -------------------------------------------------------------
    Entry(
        slug="ec2-stop-instances",
        action_id="aws:ec2:stop-instances",
        description="Stop EC2 instances via AWS FIS; workloads on them "
        "terminate and the ASG (if any) replaces per its policy.",
        category="compute",
        target_type="vm",
        fault_family="stop",
        intensity="extreme",
        expected_signal="pod_restart",
        params={"action_id": "aws:ec2:stop-instances", "startInstancesAfterDuration": "PT10M"},
        rollback_note="`aws ec2 start-instances` (FIS auto-starts if the duration is set).",
    ),
    Entry(
        slug="ec2-reboot-instances",
        action_id="aws:ec2:reboot-instances",
        description="Reboot EC2 instances via AWS FIS.",
        category="compute",
        target_type="vm",
        fault_family="stop",
        intensity="high",
        expected_signal="pod_restart",
        params={"action_id": "aws:ec2:reboot-instances"},
        rollback_note="Reboot is one-way; monitor instance back to running.",
    ),
    Entry(
        slug="ec2-terminate-instances",
        action_id="aws:ec2:terminate-instances",
        description="Terminate EC2 instances via AWS FIS; ASG replaces "
        "per its policy (irreversible on the specific instance).",
        category="compute",
        target_type="vm",
        fault_family="stop",
        intensity="extreme",
        expected_signal="pod_restart",
        params={"action_id": "aws:ec2:terminate-instances"},
        rollback_note="No rollback for the specific instance; ASG replaces.",
    ),
    Entry(
        slug="ec2-send-spot-instance-interruptions",
        action_id="aws:ec2:send-spot-instance-interruptions",
        description="Send Spot instance interruption notices (2-min warning) "
        "via AWS FIS; workload sees graceful preemption path.",
        category="compute",
        target_type="vm",
        fault_family="preempt",
        intensity="high",
        expected_signal="spot_preempt_cascade",
        params={"action_id": "aws:ec2:send-spot-instance-interruptions"},
        rollback_note="Interruption is one-way; workload must handle it.",
    ),
    # -- SSM (agent-based faults on EC2) --------------------------------
    Entry(
        slug="ssm-cpu-stress",
        action_id="aws:ssm:send-command/AWSFIS-Run-CPU-Stress",
        description="Sustain CPU pressure on EC2 via SSM Run-Command (AWSFIS-Run-CPU-Stress).",
        category="compute",
        target_type="vm",
        fault_family="saturate",
        intensity="high",
        expected_signal="host_cpu",
        params={
            "action_id": "aws:ssm:send-command",
            "document": "AWSFIS-Run-CPU-Stress",
            "cpu_percent": "80",
        },
        rollback_note="SSM stops the stress at duration end.",
    ),
    Entry(
        slug="ssm-memory-stress",
        action_id="aws:ssm:send-command/AWSFIS-Run-Memory-Stress",
        description="Sustain memory pressure on EC2 via SSM Run-Command "
        "(AWSFIS-Run-Memory-Stress).",
        category="resource_saturation",
        target_type="vm",
        fault_family="saturate",
        intensity="high",
        expected_signal="host_memory",
        params={
            "action_id": "aws:ssm:send-command",
            "document": "AWSFIS-Run-Memory-Stress",
            "percent": "80",
        },
        rollback_note="SSM releases memory at duration end.",
    ),
    Entry(
        slug="ssm-network-latency",
        action_id="aws:ssm:send-command/AWSFIS-Run-Network-Latency",
        description="Add outbound network latency on EC2 via SSM Run-Command "
        "(AWSFIS-Run-Network-Latency).",
        category="network",
        target_type="vm",
        fault_family="delay",
        intensity="high",
        expected_signal="gateway_latency",
        params={
            "action_id": "aws:ssm:send-command",
            "document": "AWSFIS-Run-Network-Latency",
            "latency_ms": "300",
        },
        rollback_note="SSM removes the tc netem rule at duration end.",
    ),
    Entry(
        slug="ssm-network-packet-loss",
        action_id="aws:ssm:send-command/AWSFIS-Run-Network-Packet-Loss",
        description="Drop packets on EC2 via SSM Run-Command (AWSFIS-Run-Network-Packet-Loss).",
        category="network",
        target_type="vm",
        fault_family="drop",
        intensity="high",
        expected_signal="request_failure",
        params={
            "action_id": "aws:ssm:send-command",
            "document": "AWSFIS-Run-Network-Packet-Loss",
            "loss_percent": "20",
        },
        rollback_note="SSM removes the drop rule at duration end.",
    ),
    Entry(
        slug="ssm-disk-fill",
        action_id="aws:ssm:send-command/AWSFIS-Run-Disk-Fill",
        description="Fill the root disk on EC2 via SSM Run-Command (AWSFIS-Run-Disk-Fill).",
        category="storage",
        target_type="disk",
        fault_family="saturate",
        intensity="extreme",
        expected_signal="host_cpu",
        params={
            "action_id": "aws:ssm:send-command",
            "document": "AWSFIS-Run-Disk-Fill",
            "percent": "95",
        },
        rollback_note="SSM removes the fill files at duration end.",
    ),
    Entry(
        slug="ssm-kill-process",
        action_id="aws:ssm:send-command/AWSFIS-Run-Kill-Process",
        description="Kill a target process on EC2 via SSM Run-Command (AWSFIS-Run-Kill-Process).",
        category="compute",
        target_type="vm",
        fault_family="stop",
        intensity="extreme",
        expected_signal="pod_restart",
        params={
            "action_id": "aws:ssm:send-command",
            "document": "AWSFIS-Run-Kill-Process",
            "process_name": "myapp",
        },
        rollback_note="Systemd / supervisor restarts the process.",
    ),
    # -- Network / VPC --------------------------------------------------
    Entry(
        slug="network-disrupt-connectivity",
        action_id="aws:network:disrupt-connectivity",
        description="Block a subnet from a target set via NACL flip; "
        "downstream endpoints see partition.",
        category="network",
        target_type="ingress",
        fault_family="deny",
        intensity="extreme",
        expected_signal="backend_health",
        params={"action_id": "aws:network:disrupt-connectivity", "scope": "all"},
        rollback_note="FIS removes the NACL rule at duration end.",
    ),
    # -- ECS / EKS ------------------------------------------------------
    Entry(
        slug="ecs-stop-task",
        action_id="aws:ecs:stop-task",
        description="Stop an ECS task via AWS FIS; the service reschedules.",
        category="compute",
        target_type="pod",
        fault_family="stop",
        intensity="high",
        expected_signal="pod_restart",
        params={"action_id": "aws:ecs:stop-task"},
        rollback_note="ECS reschedules per the service policy.",
    ),
    Entry(
        slug="eks-pod-cpu-stress",
        action_id="aws:eks:pod-cpu-stress",
        description="Inject CPU stress into EKS pods via AWS FIS.",
        category="compute",
        target_type="pod",
        fault_family="saturate",
        intensity="high",
        expected_signal="node_cpu",
        params={"action_id": "aws:eks:pod-cpu-stress", "cpu_percent": "90"},
        rollback_note="FIS removes the stress at duration end.",
        blast_radius_cap=3,
    ),
    Entry(
        slug="eks-pod-network-latency",
        action_id="aws:eks:pod-network-latency",
        description="Inject network latency into EKS pods via AWS FIS.",
        category="network",
        target_type="pod",
        fault_family="delay",
        intensity="high",
        expected_signal="gateway_latency",
        params={"action_id": "aws:eks:pod-network-latency", "latency_ms": "300"},
        rollback_note="FIS removes the tc netem rule at duration end.",
        blast_radius_cap=2,
    ),
    # -- RDS / Aurora ---------------------------------------------------
    Entry(
        slug="rds-failover-db-cluster",
        action_id="aws:rds:failover-db-cluster",
        description="Force an RDS / Aurora cluster failover via AWS FIS; "
        "clients see transient connection errors and DNS repoint.",
        category="dependency",
        target_type="db",
        fault_family="stop",
        intensity="extreme",
        expected_signal="request_failure",
        params={"action_id": "aws:rds:failover-db-cluster"},
        rollback_note="Failback via a second failover if needed.",
    ),
    Entry(
        slug="rds-reboot-db-instances",
        action_id="aws:rds:reboot-db-instances",
        description="Reboot RDS instances via AWS FIS.",
        category="dependency",
        target_type="db",
        fault_family="stop",
        intensity="high",
        expected_signal="request_failure",
        params={"action_id": "aws:rds:reboot-db-instances"},
        rollback_note="Reboot is one-way; monitor instance state.",
    ),
    # -- S3 -------------------------------------------------------------
    Entry(
        slug="s3-bucket-pause-replication",
        action_id="aws:s3:bucket-pause-replication",
        description="Pause S3 bucket replication via AWS FIS; downstream "
        "consumers of the replicated bucket lag.",
        category="dependency",
        target_type="disk",
        fault_family="throttle",
        intensity="high",
        expected_signal="weights_fetch_stall",
        params={"action_id": "aws:s3:bucket-pause-replication"},
        rollback_note="FIS resumes replication at duration end.",
    ),
    # -- Additional EC2 / ASG / ECS / EKS / Network / Data / Serverless --
    Entry(
        slug="ec2-asg-insufficient-instance-capacity",
        action_id="aws:ec2:asg-insufficient-instance-capacity-error",
        description="Inject InsufficientInstanceCapacity errors on Auto Scaling Group launches.",
        category="quota",
        target_type="vmss",
        fault_family="quota_shrink",
        intensity="high",
        expected_signal="rollout_stall",
        params={"action_id": "aws:ec2:asg-insufficient-instance-capacity-error"},
        rollback_note="FIS clears the capacity block at duration end.",
    ),
    Entry(
        slug="ecs-task-cpu-stress",
        action_id="aws:ecs:task-cpu-stress",
        description="Inject CPU saturation into running ECS tasks via SSM agent.",
        category="compute",
        target_type="pod",
        fault_family="saturate",
        intensity="high",
        expected_signal="node_cpu",
        params={"action_id": "aws:ecs:task-cpu-stress", "cpu_percent": "90"},
        rollback_note="FIS stops the task CPU stressor at duration end.",
    ),
    Entry(
        slug="ecs-task-io-stress",
        action_id="aws:ecs:task-io-stress",
        description="Sustain storage I/O pressure inside ECS container tasks.",
        category="storage",
        target_type="disk",
        fault_family="saturate",
        intensity="high",
        expected_signal="host_cpu",
        params={"action_id": "aws:ecs:task-io-stress", "workers": "4"},
        rollback_note="FIS stops the task I/O stressor at duration end.",
    ),
    Entry(
        slug="ecs-task-kill-process",
        action_id="aws:ecs:task-kill-process",
        description="Kill the target application process inside an ECS task container.",
        category="compute",
        target_type="pod",
        fault_family="stop",
        intensity="high",
        expected_signal="pod_restart",
        params={"action_id": "aws:ecs:task-kill-process", "process_name": "app"},
        rollback_note="ECS task supervisor or service scheduler restarts the container.",
    ),
    Entry(
        slug="ecs-task-network-latency",
        action_id="aws:ecs:task-network-latency",
        description="Add outbound network latency to ECS task network interfaces.",
        category="network",
        target_type="pod",
        fault_family="delay",
        intensity="high",
        expected_signal="gateway_latency",
        params={"action_id": "aws:ecs:task-network-latency", "latency_ms": "250"},
        rollback_note="FIS removes the task netem rule at duration end.",
    ),
    Entry(
        slug="ecs-task-network-packet-loss",
        action_id="aws:ecs:task-network-packet-loss",
        description="Drop outbound packets on ECS task network interfaces.",
        category="network",
        target_type="pod",
        fault_family="drop",
        intensity="high",
        expected_signal="request_failure",
        params={"action_id": "aws:ecs:task-network-packet-loss", "loss_percent": "20"},
        rollback_note="FIS removes the task packet-loss rule at duration end.",
    ),
    Entry(
        slug="eks-terminate-nodegroup-instances",
        action_id="aws:eks:terminate-nodegroup-instances",
        description="Terminate a percentage of managed EKS nodegroup instances.",
        category="compute",
        target_type="node",
        fault_family="stop",
        intensity="extreme",
        expected_signal="pod_restart",
        params={"action_id": "aws:eks:terminate-nodegroup-instances", "percent": "50"},
        rollback_note="Managed nodegroup provisions replacement worker nodes.",
    ),
    Entry(
        slug="eks-pod-delete",
        action_id="aws:eks:pod-delete",
        description="Delete targeted EKS Pods to validate ReplicaSet and PDB recovery.",
        category="compute",
        target_type="pod",
        fault_family="stop",
        intensity="high",
        expected_signal="pod_restart",
        params={"action_id": "aws:eks:pod-delete", "grace_period_seconds": "0"},
        rollback_note="ReplicaSet controller recreates the deleted Pods.",
    ),
    Entry(
        slug="eks-pod-memory-stress",
        action_id="aws:eks:pod-memory-stress",
        description="Inject memory saturation into EKS Pods via AWS FIS.",
        category="resource_saturation",
        target_type="pod",
        fault_family="saturate",
        intensity="high",
        expected_signal="host_memory",
        params={"action_id": "aws:eks:pod-memory-stress", "percent": "85"},
        rollback_note="FIS releases allocated Pod memory at duration end.",
    ),
    Entry(
        slug="eks-pod-io-stress",
        action_id="aws:eks:pod-io-stress",
        description="Inject filesystem I/O saturation into EKS Pods via AWS FIS.",
        category="storage",
        target_type="disk",
        fault_family="saturate",
        intensity="high",
        expected_signal="host_cpu",
        params={"action_id": "aws:eks:pod-io-stress", "percent": "80"},
        rollback_note="FIS stops the Pod I/O workers at duration end.",
    ),
    Entry(
        slug="eks-pod-network-packet-loss",
        action_id="aws:eks:pod-network-packet-loss",
        description="Drop outbound packets from targeted EKS Pods via AWS FIS.",
        category="network",
        target_type="pod",
        fault_family="drop",
        intensity="high",
        expected_signal="request_failure",
        params={"action_id": "aws:eks:pod-network-packet-loss", "loss_percent": "25"},
        rollback_note="FIS removes the Pod netem loss rule at duration end.",
    ),
    Entry(
        slug="eks-pod-network-blackhole",
        action_id="aws:eks:pod-network-blackhole-port",
        description="Drop traffic on a specific port for targeted EKS Pods.",
        category="network",
        target_type="pod",
        fault_family="deny",
        intensity="extreme",
        expected_signal="backend_health",
        params={"action_id": "aws:eks:pod-network-blackhole-port", "port": "8080"},
        rollback_note="FIS removes the port blackhole rule at duration end.",
    ),
    Entry(
        slug="network-route-table-disrupt",
        action_id="aws:network:route-table-disrupt-cross-region-connectivity",
        description="Disrupt cross-region or peered subnet route-table entries.",
        category="network",
        target_type="egress",
        fault_family="misroute",
        intensity="extreme",
        expected_signal="request_failure",
        params={"action_id": "aws:network:route-table-disrupt-cross-region-connectivity"},
        rollback_note="FIS restores the original route-table entries at duration end.",
    ),
    Entry(
        slug="network-transit-gateway-disrupt",
        action_id="aws:network:transit-gateway-disrupt-cross-region-connectivity",
        description="Blackhole Transit Gateway attachments across peered networks.",
        category="network",
        target_type="ingress",
        fault_family="deny",
        intensity="extreme",
        expected_signal="backend_health",
        params={"action_id": "aws:network:transit-gateway-disrupt-cross-region-connectivity"},
        rollback_note="FIS restores Transit Gateway route propagation at duration end.",
    ),
    Entry(
        slug="ebs-volume-io-latency",
        action_id="aws:ebs:volume-io-latency",
        description="Inject read and write I/O latency onto attached block storage volumes.",
        category="storage",
        target_type="disk",
        fault_family="delay",
        intensity="high",
        expected_signal="gateway_latency",
        params={"action_id": "aws:ebs:volume-io-latency", "latency_ms": "150"},
        rollback_note="FIS clears the volume I/O latency injection at duration end.",
    ),
    Entry(
        slug="ebs-volume-io-pause",
        action_id="aws:ebs:pause-volume-io",
        description="Pause all block I/O operations on an attached EBS volume.",
        category="storage",
        target_type="disk",
        fault_family="hang",
        intensity="extreme",
        expected_signal="resource_availability",
        params={"action_id": "aws:ebs:pause-volume-io"},
        rollback_note="FIS resumes volume I/O at duration end.",
    ),
    Entry(
        slug="dynamodb-global-table-pause-replication",
        action_id="aws:dynamodb:global-table-pause-replication",
        description="Pause cross-region replication on a global NoSQL table.",
        category="dependency",
        target_type="db",
        fault_family="throttle",
        intensity="high",
        expected_signal="request_failure",
        params={"action_id": "aws:dynamodb:global-table-pause-replication"},
        rollback_note="FIS resumes global table replication at duration end.",
    ),
    Entry(
        slug="elasticache-failover-shard",
        action_id="aws:elasticache:failover-shard",
        description="Force a primary-to-replica shard failover on a Redis cluster.",
        category="dependency",
        target_type="cache",
        fault_family="stop",
        intensity="high",
        expected_signal="request_failure",
        params={"action_id": "aws:elasticache:failover-shard"},
        rollback_note="Cluster promotes replica and reconnects clients.",
    ),
    Entry(
        slug="elasticache-interrupt-cluster-power",
        action_id="aws:elasticache:interrupt-cluster-power",
        description="Interrupt node power on a distributed cache cluster.",
        category="dependency",
        target_type="cache",
        fault_family="stop",
        intensity="extreme",
        expected_signal="backend_health",
        params={"action_id": "aws:elasticache:interrupt-cluster-power"},
        rollback_note="FIS restores cache node power at duration end.",
    ),
    Entry(
        slug="lambda-invocation-delay",
        action_id="aws:lambda:invocation-add-delay",
        description="Inject startup and execution latency into serverless function invocations.",
        category="traffic",
        target_type="pod",
        fault_family="delay",
        intensity="high",
        expected_signal="gateway_latency",
        params={"action_id": "aws:lambda:invocation-add-delay", "delay_ms": "2000"},
        rollback_note="FIS removes the invocation fault extension override.",
    ),
    Entry(
        slug="lambda-invocation-http-error",
        action_id="aws:lambda:invocation-error",
        description="Force serverless function invocations to fail with unhandled errors.",
        category="compute",
        target_type="pod",
        fault_family="stop",
        intensity="high",
        expected_signal="request_failure",
        params={"action_id": "aws:lambda:invocation-error", "percentage": "100"},
        rollback_note="FIS disables the invocation fault injection at duration end.",
    ),
    Entry(
        slug="lambda-tmp-disk-fill",
        action_id="aws:lambda:invocation-write-ephemeral-storage",
        description="Exhaust serverless ephemeral /tmp disk capacity during invocation.",
        category="storage",
        target_type="disk",
        fault_family="saturate",
        intensity="high",
        expected_signal="pod_failed",
        params={"action_id": "aws:lambda:invocation-write-ephemeral-storage", "percent": "95"},
        rollback_note="FIS clears the ephemeral storage fill at duration end.",
    ),
    Entry(
        slug="iam-role-access-denied",
        action_id="aws:iam:deny-role-access",
        description="Attach a temporary explicit Deny policy to a workload IAM role.",
        category="identity",
        target_type="identity",
        fault_family="deny",
        intensity="extreme",
        expected_signal="request_failure",
        params={"action_id": "aws:iam:deny-role-access"},
        rollback_note="FIS detaches the temporary Deny policy at duration end.",
    ),
    Entry(
        slug="sqs-queue-pause-delivery",
        action_id="aws:sqs:pause-message-delivery",
        description="Pause message delivery from a queue to downstream consumers.",
        category="dependency",
        target_type="ingress",
        fault_family="throttle",
        intensity="high",
        expected_signal="gateway_latency",
        params={"action_id": "aws:sqs:pause-message-delivery"},
        rollback_note="FIS restores queue message delivery at duration end.",
    ),
    Entry(
        slug="bedrock-model-invocation-throttle",
        action_id="aws:bedrock:model-invocation-throttle",
        description="Return HTTP 429 throttling exceptions on managed LLM endpoint calls.",
        category="quota",
        target_type="llm_endpoint",
        fault_family="throttle",
        intensity="high",
        expected_signal="rate_limit",
        params={"action_id": "aws:bedrock:model-invocation-throttle"},
        rollback_note="FIS removes the model throttling rule at duration end.",
    ),
)


def _validate_entry(e: Entry) -> None:
    if not _SLUG_PATTERN.fullmatch(e.slug):
        raise ValueError("invalid_slug")
    if not e.action_id.startswith("aws:"):
        raise ValueError("unsupported_action_id")
    if e.category not in _ALLOWED_CATEGORIES:
        raise ValueError("unsupported_category")
    if e.target_type not in _ALLOWED_TARGET_TYPES:
        raise ValueError("unsupported_target_type")
    if e.fault_family not in _ALLOWED_FAULT_FAMILIES:
        raise ValueError("unsupported_fault_family")
    if e.intensity not in _ALLOWED_INTENSITIES:
        raise ValueError("unsupported_intensity")
    if e.blast_radius_cap < 1:
        raise ValueError("invalid_blast_radius_cap")
    if not e.description.strip() or not e.rollback_note.strip():
        raise ValueError("missing_description_or_rollback_note")
    signal = known_signals().get(e.expected_signal)
    if signal is None:
        raise ValueError("unknown_expected_signal")
    if signal.role is SignalRole.RCA_ONLY:
        raise ValueError("rca_only_signal_not_scenario_eligible")


def _to_body(e: Entry) -> dict[str, object]:
    _validate_entry(e)
    return {
        "id": f"chaos.aws-fis.{e.slug}",
        "version": 1,
        "provenance": {
            "source": "aws-fis",
            "source_url": "https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html",
            "source_ref": e.action_id,
            "synthesis_method": "collected",
        },
        "category": e.category,
        "target_type": e.target_type,
        "fault_family": e.fault_family,
        "intensity": e.intensity,
        "duration_seconds": _ALERT_WINDOW_S if e.intensity != "extreme" else _ALERT_WINDOW_S * 2,
        "expected_signal": e.expected_signal,
        "injector": "cross-csp-reference",
        "blast_radius_cap": e.blast_radius_cap,
        "rollback_note": e.rollback_note,
        "gates": {"shadow_status": "pending", "enforce_status": None},
        "requires_hardware": False,
        "description": e.description,
        "params": dict(e.params),
        "tags": ["aws-fis"],
    }


def main() -> int:
    slugs = [e.slug for e in _ENTRIES]
    if len(slugs) != len(set(slugs)):
        raise ValueError("duplicate_slug")
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    valid_names = {f"{e.slug}.yaml" for e in _ENTRIES}
    for existing in _OUT_DIR.glob("*.yaml"):
        if existing.name not in valid_names:
            existing.unlink()
    written = 0
    for e in _ENTRIES:
        path = _OUT_DIR / f"{e.slug}.yaml"
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(_to_body(e), f, sort_keys=False, default_flow_style=False)
        written += 1
    print(f"wrote {written} AWS FIS scenarios -> {_OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
