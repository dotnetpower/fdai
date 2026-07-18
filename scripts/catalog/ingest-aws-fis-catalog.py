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
from dataclasses import dataclass

import yaml

_HERE = pathlib.Path(__file__).resolve()
_REPO_ROOT = next(parent for parent in _HERE.parents if (parent / "pyproject.toml").is_file())
_OUT_DIR = _REPO_ROOT / "rule-catalog" / "chaos-scenarios" / "collected" / "aws-fis"
_ALERT_WINDOW_S = 360.0


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
)


def _to_body(e: Entry) -> dict:
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
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
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
