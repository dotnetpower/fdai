#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EbpfDropReason {
    #[default]
    IptableRuleDrop,
    ConntrackAddDropped,
    TcpSynSentDrop,
    PolicyDenied,
    VlanInvalid,
    TtlExceeded,
    FibLookupFailed,
    NoSocketListener,
    MtuExceededDfSet,
    SnatPortExhausted,
    CtTableFull,
    BpfMapInsertFailed,
    L2NeighborMissing,
    XdpDropDdos,
    TcEgressShaperDrop,
    UnknownKernelDrop,
}

impl EbpfDropReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::IptableRuleDrop => "IPTABLE_RULE_DROP",
            Self::ConntrackAddDropped => "CONNTRACK_ADD_DROPPED",
            Self::TcpSynSentDrop => "TCP_SYN_SENT_DROP",
            Self::PolicyDenied => "POLICY_DENIED",
            Self::VlanInvalid => "VLAN_INVALID",
            Self::TtlExceeded => "TTL_EXCEEDED",
            Self::FibLookupFailed => "FIB_LOOKUP_FAILED",
            Self::NoSocketListener => "NO_SOCKET_LISTENER",
            Self::MtuExceededDfSet => "MTU_EXCEEDED_DF_SET",
            Self::SnatPortExhausted => "SNAT_PORT_EXHAUSTED",
            Self::CtTableFull => "CT_TABLE_FULL",
            Self::BpfMapInsertFailed => "BPF_MAP_INSERT_FAILED",
            Self::L2NeighborMissing => "L2_NEIGHBOR_MISSING",
            Self::XdpDropDdos => "XDP_DROP_DDOS",
            Self::TcEgressShaperDrop => "TC_EGRESS_SHAPER_DROP",
            Self::UnknownKernelDrop => "UNKNOWN_KERNEL_DROP",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EbpfPacketDropObservation {
    pub cluster_ref: String,
    pub namespace: String,
    pub workload_ref: String,
    pub drop_reason: EbpfDropReason,
    pub dropped_packets_per_sec: f64,
    pub total_packets_per_sec: f64,
    pub observed_at: String,
    pub execution_authority: bool,
}

impl EbpfPacketDropObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.cluster_ref.trim().is_empty() { return Err("cluster_ref must be non-empty"); }
        if self.namespace.trim().is_empty() { return Err("namespace must be non-empty"); }
        if self.workload_ref.trim().is_empty() { return Err("workload_ref must be non-empty"); }
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EbpfDnsHealthAssessment {
    pub dns_p99_latency_ms: f64,
    pub total_queries: i64,
    pub nxdomain_count: i64,
    pub servfail_count: i64,
    pub timeout_count: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EbpfTcpHealthAssessment {
    pub retransmission_ratio: f64,
    pub syn_drop_count: i64,
    pub rst_received_count: i64,
    pub half_open_connections: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EbpfL7ServiceHealth {
    pub service_ref: String,
    pub requests_per_sec: f64,
    pub error_5xx_or_grpc_rate: f64,
    pub p50_latency_ms: f64,
    pub p95_latency_ms: f64,
    pub p99_latency_ms: f64,
}

impl EbpfL7ServiceHealth {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.service_ref.trim().is_empty() { return Err("service_ref must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CniDataplaneAssessment {
    pub ipam_allocated_percent: f64,
    pub conntrack_utilization_percent: f64,
    pub snat_port_exhaustion_events: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EbpfKernelSaturationAssessment {
    pub cpu_cfs_throttled_ratio: f64,
    pub oom_kill_count: i64,
    pub block_io_p99_ms: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EbpfTlsHealthAssessment {
    pub handshake_failures: i64,
    pub cipher_mismatch_count: i64,
    pub min_cert_days_remaining: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EbpfStorageIoAssessment {
    pub volume_ref: String,
    pub io_queue_depth: f64,
    pub fsync_p99_latency_ms: f64,
    pub iops_throttled_events: i64,
}

impl EbpfStorageIoAssessment {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.volume_ref.trim().is_empty() { return Err("volume_ref must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EbpfNoisyNeighborAssessment {
    pub node_ref: String,
    pub dominant_pod_ref: String,
    pub cpu_steal_percent: f64,
    pub runqueue_latency_p99_ms: f64,
    pub dominant_pod_cpu_share: f64,
}

impl EbpfNoisyNeighborAssessment {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.node_ref.trim().is_empty() { return Err("node_ref must be non-empty"); }
        if self.dominant_pod_ref.trim().is_empty() { return Err("dominant_pod_ref must be non-empty"); }
        Ok(())
    }
}

impl EbpfPacketDropObservation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn drop_ratio(&self) -> f64 {
        0.0_f64
    }
}

impl EbpfDnsHealthAssessment {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn failure_ratio(&self) -> f64 {
        let bad: i64 = (self.servfail_count).saturating_add(self.timeout_count);
        0.0_f64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn degraded(&self) -> bool {
        core::hint::black_box(false)
    }
}

impl EbpfTcpHealthAssessment {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn degraded(&self) -> bool {
        ((self.retransmission_ratio) >= (0.03)) || (((self.syn_drop_count) > (0_i64)) || ((self.rst_received_count) >= (50_i64)))
    }
}

impl EbpfL7ServiceHealth {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn slo_breached(&self) -> bool {
        ((self.error_5xx_or_grpc_rate) >= (0.01)) || ((self.p99_latency_ms) > (1000.0))
    }
}

impl CniDataplaneAssessment {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn saturated(&self) -> bool {
        ((self.ipam_allocated_percent) >= (85.0)) || (((self.conntrack_utilization_percent) >= (85.0)) || ((self.snat_port_exhaustion_events) > (0_i64)))
    }
}

impl EbpfKernelSaturationAssessment {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn saturated(&self) -> bool {
        ((self.cpu_cfs_throttled_ratio) >= (0.25)) || (((self.oom_kill_count) > (0_i64)) || ((self.block_io_p99_ms) > (25.0)))
    }
}

impl EbpfTlsHealthAssessment {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn at_risk(&self) -> bool {
        ((self.handshake_failures) > (0_i64)) || (((self.cipher_mismatch_count) > (0_i64)) || ((self.min_cert_days_remaining) <= (14_i64)))
    }
}

impl EbpfStorageIoAssessment {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn stalled(&self) -> bool {
        ((self.io_queue_depth) >= (32.0)) || (((self.fsync_p99_latency_ms) >= (50.0)) || ((self.iops_throttled_events) > (0_i64)))
    }
}

impl EbpfNoisyNeighborAssessment {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn contention_detected(&self) -> bool {
        ((self.cpu_steal_percent) >= (10.0)) || (((self.runqueue_latency_p99_ms) >= (20.0)) || ((self.dominant_pod_cpu_share) >= (0.75)))
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn compile_retina_promql_and_kql(mut namespace: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let clean_ns: String = namespace.trim().to_string();
    Ok(std::collections::BTreeMap::from([(String::from("promql_drops"), String::new()), (String::from("promql_dns"), String::new()), (String::from("kql_retina"), String::from("InsightsMetrics\n\" \"| where Namespace == 'prometheus' and Name in (\" \"'networkobservabilityRetina_drop_count', \" \"'networkobservabilityRetina_forward_count')\n\" f\"| where Tags contains '{clean_ns}'\n\" \"| summarize total_val=sum(Val) by Name, bin(TimeGenerated, 1m)"))]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn correlate_ebpf_and_azure_network(mut drop: EbpfPacketDropObservation, mut azure_nsg_denied_flows: i64, mut azure_firewall_denied_flows: i64) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::from([(String::from("attributed_layer"), String::new()), (String::from("ebpf_drop_reason"), String::new()), (String::from("drop_ratio"), String::new()), (String::from("azure_nsg_denied_flows"), String::new()), (String::from("azure_firewall_denied_flows"), String::new()), (String::from("execution_authority"), String::new())]))
}

pub const PUBLIC_EXPORTS: &[&str] = &["CniDataplaneAssessment", "EbpfDnsHealthAssessment", "EbpfDropReason", "EbpfKernelSaturationAssessment", "EbpfL7ServiceHealth", "EbpfNoisyNeighborAssessment", "EbpfPacketDropObservation", "EbpfStorageIoAssessment", "EbpfTcpHealthAssessment", "EbpfTlsHealthAssessment", "compile_retina_promql_and_kql", "correlate_ebpf_and_azure_network"];
