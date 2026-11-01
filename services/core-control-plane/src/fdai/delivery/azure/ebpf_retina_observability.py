"""eBPF, Microsoft Retina & Cilium Hubble Kernel/Network Observability (Rounds 5-8, E013-E024).

Implements zero-instrumentation kernel and container networking observability for AKS
and Linux hosts:
- E013: 16-member Retina & Cilium Hubble eBPF packet drop taxonomy (``EbpfDropReason``)
- E014: eBPF packet drop & flow anomaly observation contract (``EbpfPacketDropObservation``)
- E015: eBPF DNS lookup latency, NXDOMAIN & SERVFAIL analyzer (``EbpfDnsHealthAssessment``)
- E016: eBPF TCP retransmission, SYN backlog & RST spike detector (``EbpfTcpHealthAssessment``)
- E017: eBPF L7 HTTP/gRPC service-mesh golden signals (``EbpfL7ServiceHealth``)
- E018: AKS CNI Overlay / Cilium IPAM, conntrack & SNAT analyzer (``CniDataplaneAssessment``)
- E019: eBPF kernel CPU CFS throttling, OOMKill & bio-latency (``EbpfKernelSaturationAssessment``)
- E020: eBPF TLS/mTLS handshake & certificate expiration detector (``EbpfTlsHealthAssessment``)
- E021: Retina & Hubble PromQL and KQL query compiler (``compile_retina_promql_and_kql``)
- E022: Cross-layer eBPF vs. NSG/Firewall correlator (``correlate_ebpf_and_azure_network``)
- E023: eBPF CSI/NVMe storage I/O queue & fsync stall detector (``EbpfStorageIoAssessment``)
- E024: eBPF node noisy-neighbor & CPU steal detector (``EbpfNoisyNeighborAssessment``)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class EbpfDropReason(StrEnum):
    """E013: Canonical Microsoft Retina & Cilium Hubble eBPF packet drop reasons."""

    IPTABLE_RULE_DROP = "IPTABLE_RULE_DROP"
    CONNTRACK_ADD_DROPPED = "CONNTRACK_ADD_DROPPED"
    TCP_SYN_SENT_DROP = "TCP_SYN_SENT_DROP"
    POLICY_DENIED = "POLICY_DENIED"
    VLAN_INVALID = "VLAN_INVALID"
    TTL_EXCEEDED = "TTL_EXCEEDED"
    FIB_LOOKUP_FAILED = "FIB_LOOKUP_FAILED"
    NO_SOCKET_LISTENER = "NO_SOCKET_LISTENER"
    MTU_EXCEEDED_DF_SET = "MTU_EXCEEDED_DF_SET"
    SNAT_PORT_EXHAUSTED = "SNAT_PORT_EXHAUSTED"
    CT_TABLE_FULL = "CT_TABLE_FULL"
    BPF_MAP_INSERT_FAILED = "BPF_MAP_INSERT_FAILED"
    L2_NEIGHBOR_MISSING = "L2_NEIGHBOR_MISSING"
    XDP_DROP_DDoS = "XDP_DROP_DDOS"
    TC_EGRESS_SHAPER_DROP = "TC_EGRESS_SHAPER_DROP"
    UNKNOWN_KERNEL_DROP = "UNKNOWN_KERNEL_DROP"


@dataclass(frozen=True, slots=True)
class EbpfPacketDropObservation:
    """E014: Bounded eBPF packet drop observation from Retina or Hubble."""

    cluster_ref: str
    namespace: str
    workload_ref: str
    drop_reason: EbpfDropReason
    dropped_packets_per_sec: float
    total_packets_per_sec: float
    observed_at: datetime
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if (
            not self.cluster_ref.strip()
            or not self.namespace.strip()
            or not self.workload_ref.strip()
        ):
            raise ValueError("EbpfPacketDropObservation identifiers MUST be non-empty")
        if self.observed_at.tzinfo is None:
            raise ValueError("EbpfPacketDropObservation.observed_at MUST be timezone-aware")
        for val in (self.dropped_packets_per_sec, self.total_packets_per_sec):
            if type(val) is bool or not math.isfinite(val) or val < 0:
                raise ValueError("Packet rates MUST be finite non-negative numbers")
        if (
            self.dropped_packets_per_sec > self.total_packets_per_sec
            and self.total_packets_per_sec > 0
        ):
            raise ValueError("dropped_packets_per_sec MUST NOT exceed total_packets_per_sec")
        if type(self.execution_authority) is not bool or self.execution_authority:
            raise ValueError("EbpfPacketDropObservation MUST have execution_authority=False")

    @property
    def drop_ratio(self) -> float:
        return (
            round(self.dropped_packets_per_sec / self.total_packets_per_sec, 4)
            if self.total_packets_per_sec > 0
            else 0.0
        )


@dataclass(frozen=True, slots=True)
class EbpfDnsHealthAssessment:
    """E015: eBPF-observed DNS lookup latency, NXDOMAIN, and SERVFAIL assessment."""

    dns_p99_latency_ms: float
    total_queries: int
    nxdomain_count: int
    servfail_count: int
    timeout_count: int

    def __post_init__(self) -> None:
        if (
            type(self.dns_p99_latency_ms) is bool
            or not math.isfinite(self.dns_p99_latency_ms)
            or self.dns_p99_latency_ms < 0
        ):
            raise ValueError("dns_p99_latency_ms MUST be a finite non-negative number")
        for cnt in (
            self.total_queries,
            self.nxdomain_count,
            self.servfail_count,
            self.timeout_count,
        ):
            if type(cnt) is not int or cnt < 0:
                raise ValueError("DNS query counts MUST be non-negative integers")

    @property
    def failure_ratio(self) -> float:
        bad = self.servfail_count + self.timeout_count
        return round(bad / self.total_queries, 4) if self.total_queries > 0 else 0.0

    @property
    def degraded(self) -> bool:
        return self.dns_p99_latency_ms > 50.0 or self.failure_ratio >= 0.02


@dataclass(frozen=True, slots=True)
class EbpfTcpHealthAssessment:
    """E016: eBPF TCP state-machine retransmission, SYN backlog, and RST surge assessment."""

    retransmission_ratio: float
    syn_drop_count: int
    rst_received_count: int
    half_open_connections: int

    def __post_init__(self) -> None:
        if (
            type(self.retransmission_ratio) is bool
            or not math.isfinite(self.retransmission_ratio)
            or not 0.0 <= self.retransmission_ratio <= 1.0
        ):
            raise ValueError("retransmission_ratio MUST be in [0, 1]")
        for cnt in (self.syn_drop_count, self.rst_received_count, self.half_open_connections):
            if type(cnt) is not int or cnt < 0:
                raise ValueError("TCP state counts MUST be non-negative integers")

    @property
    def degraded(self) -> bool:
        return (
            self.retransmission_ratio >= 0.03
            or self.syn_drop_count > 0
            or self.rst_received_count >= 50
        )


@dataclass(frozen=True, slots=True)
class EbpfL7ServiceHealth:
    """E017: Zero-instrumentation eBPF L7 HTTP/gRPC golden signals."""

    service_ref: str
    requests_per_sec: float
    error_5xx_or_grpc_rate: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float

    def __post_init__(self) -> None:
        if not self.service_ref.strip():
            raise ValueError("service_ref MUST be non-empty")
        for val in (
            self.requests_per_sec,
            self.error_5xx_or_grpc_rate,
            self.p50_latency_ms,
            self.p95_latency_ms,
            self.p99_latency_ms,
        ):
            if type(val) is bool or not math.isfinite(val) or val < 0:
                raise ValueError("EbpfL7ServiceHealth metrics MUST be finite non-negative numbers")

    @property
    def slo_breached(self) -> bool:
        return self.error_5xx_or_grpc_rate >= 0.01 or self.p99_latency_ms > 1000.0


@dataclass(frozen=True, slots=True)
class CniDataplaneAssessment:
    """E018: AKS Azure CNI Overlay / Cilium IPAM, conntrack, and SNAT port utilization."""

    ipam_allocated_percent: float
    conntrack_utilization_percent: float
    snat_port_exhaustion_events: int

    def __post_init__(self) -> None:
        for pct in (self.ipam_allocated_percent, self.conntrack_utilization_percent):
            if type(pct) is bool or not math.isfinite(pct) or not 0.0 <= pct <= 100.0:
                raise ValueError("CNI utilization percentages MUST be in [0, 100]")
        if (
            type(self.snat_port_exhaustion_events) is not int
            or self.snat_port_exhaustion_events < 0
        ):
            raise ValueError("snat_port_exhaustion_events MUST be a non-negative integer")

    @property
    def saturated(self) -> bool:
        return (
            self.ipam_allocated_percent >= 85.0
            or self.conntrack_utilization_percent >= 85.0
            or self.snat_port_exhaustion_events > 0
        )


@dataclass(frozen=True, slots=True)
class EbpfKernelSaturationAssessment:
    """E019: eBPF kernel CPU CFS throttling, OOMKill, and block I/O bio-latency."""

    cpu_cfs_throttled_ratio: float
    oom_kill_count: int
    block_io_p99_ms: float

    def __post_init__(self) -> None:
        if (
            type(self.cpu_cfs_throttled_ratio) is bool
            or not math.isfinite(self.cpu_cfs_throttled_ratio)
            or not 0.0 <= self.cpu_cfs_throttled_ratio <= 1.0
        ):
            raise ValueError("cpu_cfs_throttled_ratio MUST be in [0, 1]")
        if type(self.oom_kill_count) is not int or self.oom_kill_count < 0:
            raise ValueError("oom_kill_count MUST be a non-negative integer")
        if (
            type(self.block_io_p99_ms) is bool
            or not math.isfinite(self.block_io_p99_ms)
            or self.block_io_p99_ms < 0
        ):
            raise ValueError("block_io_p99_ms MUST be finite and non-negative")

    @property
    def saturated(self) -> bool:
        return (
            self.cpu_cfs_throttled_ratio >= 0.25
            or self.oom_kill_count > 0
            or self.block_io_p99_ms > 25.0
        )


@dataclass(frozen=True, slots=True)
class EbpfTlsHealthAssessment:
    """E020: eBPF TLS/mTLS handshake failure and certificate expiration assessment."""

    handshake_failures: int
    cipher_mismatch_count: int
    min_cert_days_remaining: int

    def __post_init__(self) -> None:
        for cnt in (self.handshake_failures, self.cipher_mismatch_count):
            if type(cnt) is not int or cnt < 0:
                raise ValueError("TLS failure counts MUST be non-negative integers")
        if type(self.min_cert_days_remaining) is not int:
            raise ValueError("min_cert_days_remaining MUST be an integer")

    @property
    def at_risk(self) -> bool:
        return (
            self.handshake_failures > 0
            or self.cipher_mismatch_count > 0
            or self.min_cert_days_remaining <= 14
        )


def compile_retina_promql_and_kql(namespace: str) -> dict[str, str]:
    """E021: Compile bounded PromQL and KQL queries for Microsoft Retina eBPF metrics."""
    clean_ns = namespace.strip()
    if not clean_ns or any(ch in clean_ns for ch in ("'", '"', ";", "{", "}")):
        raise ValueError("Invalid Kubernetes namespace for Retina query compilation")
    return {
        "promql_drops": (
            f'sum(rate(networkobservabilityRetina_drop_count{{namespace="{clean_ns}"}}[5m]))'
            " by (reason)"
        ),
        "promql_dns": (
            f'sum(rate(networkobservabilityRetina_dns_response_count{{namespace="{clean_ns}"}}[5m]))'
            " by (rcode)"
        ),
        "kql_retina": (
            "InsightsMetrics\n"
            "| where Namespace == 'prometheus' and Name in ("
            "'networkobservabilityRetina_drop_count', "
            "'networkobservabilityRetina_forward_count')\n"
            f"| where Tags contains '{clean_ns}'\n"
            "| summarize total_val=sum(Val) by Name, bin(TimeGenerated, 1m)"
        ),
    }


def correlate_ebpf_and_azure_network(
    *,
    drop: EbpfPacketDropObservation,
    azure_nsg_denied_flows: int,
    azure_firewall_denied_flows: int,
) -> dict[str, object]:
    """E022: Attribute network drops between in-cluster eBPF/iptables and Azure NSG/Firewall."""
    if (
        type(azure_nsg_denied_flows) is not int
        or type(azure_firewall_denied_flows) is not int
        or azure_nsg_denied_flows < 0
        or azure_firewall_denied_flows < 0
    ):
        raise ValueError("Azure network denied flow counts MUST be non-negative integers")
    if (
        drop.drop_reason in {EbpfDropReason.POLICY_DENIED, EbpfDropReason.IPTABLE_RULE_DROP}
        and azure_nsg_denied_flows == 0
    ):
        layer = "kubernetes_network_policy_or_iptables"
    elif azure_firewall_denied_flows > 0:
        layer = "azure_firewall_rule"
    elif azure_nsg_denied_flows > 0:
        layer = "azure_nsg_security_rule"
    else:
        layer = "kernel_datapath_or_conntrack"
    return {
        "attributed_layer": layer,
        "ebpf_drop_reason": drop.drop_reason.value,
        "drop_ratio": drop.drop_ratio,
        "azure_nsg_denied_flows": azure_nsg_denied_flows,
        "azure_firewall_denied_flows": azure_firewall_denied_flows,
        "execution_authority": False,
    }


@dataclass(frozen=True, slots=True)
class EbpfStorageIoAssessment:
    """E023: eBPF CSI/NVMe block storage queue depth and fsync stall assessment."""

    volume_ref: str
    io_queue_depth: float
    fsync_p99_latency_ms: float
    iops_throttled_events: int

    def __post_init__(self) -> None:
        if not self.volume_ref.strip():
            raise ValueError("volume_ref MUST be non-empty")
        for val in (self.io_queue_depth, self.fsync_p99_latency_ms):
            if type(val) is bool or not math.isfinite(val) or val < 0:
                raise ValueError("Storage I/O metrics MUST be finite non-negative numbers")
        if type(self.iops_throttled_events) is not int or self.iops_throttled_events < 0:
            raise ValueError("iops_throttled_events MUST be a non-negative integer")

    @property
    def stalled(self) -> bool:
        return (
            self.io_queue_depth >= 32.0
            or self.fsync_p99_latency_ms >= 50.0
            or self.iops_throttled_events > 0
        )


@dataclass(frozen=True, slots=True)
class EbpfNoisyNeighborAssessment:
    """E024: eBPF node-level noisy-neighbor, CPU steal, and LLC/NUMA contention detector."""

    node_ref: str
    dominant_pod_ref: str
    cpu_steal_percent: float
    runqueue_latency_p99_ms: float
    dominant_pod_cpu_share: float

    def __post_init__(self) -> None:
        if not self.node_ref.strip() or not self.dominant_pod_ref.strip():
            raise ValueError("node_ref and dominant_pod_ref MUST be non-empty")
        for val in (
            self.cpu_steal_percent,
            self.runqueue_latency_p99_ms,
            self.dominant_pod_cpu_share,
        ):
            if type(val) is bool or not math.isfinite(val) or val < 0:
                raise ValueError("Noisy-neighbor metrics MUST be finite non-negative numbers")

    @property
    def contention_detected(self) -> bool:
        return (
            self.cpu_steal_percent >= 10.0
            or self.runqueue_latency_p99_ms >= 20.0
            or self.dominant_pod_cpu_share >= 0.75
        )


__all__ = [
    "CniDataplaneAssessment",
    "EbpfDnsHealthAssessment",
    "EbpfDropReason",
    "EbpfKernelSaturationAssessment",
    "EbpfL7ServiceHealth",
    "EbpfNoisyNeighborAssessment",
    "EbpfPacketDropObservation",
    "EbpfStorageIoAssessment",
    "EbpfTcpHealthAssessment",
    "EbpfTlsHealthAssessment",
    "compile_retina_promql_and_kql",
    "correlate_ebpf_and_azure_network",
]
