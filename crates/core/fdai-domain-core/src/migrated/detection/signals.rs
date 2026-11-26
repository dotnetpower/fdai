#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SignalRole {
    #[default]
    Scenario,
    RcaOnly,
}

impl SignalRole {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Scenario => "scenario",
            Self::RcaOnly => "rca_only",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SignalSpec {
    pub signal: String,
    pub description: String,
    pub tier_hint: String,
    pub rca_hint: String,
    pub role: SignalRole,
}

pub const SIGNAL_NODE_CPU: &str = "node_cpu";
pub const SIGNAL_POD_RESTART: &str = "pod_restart";
pub const SIGNAL_ROLLOUT_STALL: &str = "rollout_stall";
pub const SIGNAL_MEMBER_HOTSPOT: &str = "member_hotspot";
pub const SIGNAL_HOST_CPU: &str = "host_cpu";
pub const SIGNAL_HOST_MEMORY: &str = "host_memory";
pub const SIGNAL_REQUEST_FAILURE: &str = "request_failure";
pub const SIGNAL_RATE_LIMIT: &str = "rate_limit";
pub const SIGNAL_GATEWAY_LATENCY: &str = "gateway_latency";
pub const SIGNAL_BACKEND_HEALTH: &str = "backend_health";
pub const SIGNAL_DB_CPU: &str = "db_cpu";
pub const SIGNAL_CONFIG_DRIFT: &str = "config_drift";
pub const SIGNAL_ALERT_TRIGGER: &str = "alert_trigger";
pub const SIGNAL_GPU_XID_EVENT: &str = "gpu_xid_event";
pub const SIGNAL_GPU_ECC_UNCORRECTABLE: &str = "gpu_ecc_uncorrectable";
pub const SIGNAL_GPU_TEMP_THROTTLE: &str = "gpu_temp_throttle";
pub const SIGNAL_GPU_POWER_THROTTLE: &str = "gpu_power_throttle";
pub const SIGNAL_GPU_PCIE_DEGRADATION: &str = "gpu_pcie_degradation";
pub const SIGNAL_GPU_VRAM_OOM: &str = "gpu_vram_oom";
pub const SIGNAL_GPU_UTIL_ZERO_WASTED: &str = "gpu_util_zero_wasted";
pub const SIGNAL_GPU_UTIL_SATURATED: &str = "gpu_util_saturated";
pub const SIGNAL_NCCL_TIMEOUT: &str = "nccl_timeout";
pub const SIGNAL_DISTRIBUTED_STRAGGLER: &str = "distributed_straggler";
pub const SIGNAL_INFERENCE_P99_SPIKE: &str = "inference_p99_spike";
pub const SIGNAL_KV_CACHE_PRESSURE: &str = "kv_cache_pressure";
pub const SIGNAL_COLD_START_LATENCY_SPIKE: &str = "cold_start_latency_spike";
pub const SIGNAL_WEIGHTS_FETCH_STALL: &str = "weights_fetch_stall";
pub const SIGNAL_SPOT_PREEMPT_CASCADE: &str = "spot_preempt_cascade";
pub const SIGNAL_GPU_SKU_MISMATCH: &str = "gpu_sku_mismatch";
pub const SIGNAL_GPU_IDLE_HOURS_WASTED: &str = "gpu_idle_hours_wasted";
pub const SIGNAL_TOKEN_SPEND_SPIKE: &str = "token_spend_spike";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn known_signals() -> std::collections::BTreeMap<String, SignalSpec> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_known_signal(mut signal: String) -> bool {
    if !(true) {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn signals_with_role(mut role: SignalRole) -> std::collections::BTreeSet<String> {
    std::collections::BTreeSet::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["SIGNAL_ALERT_TRIGGER", "SIGNAL_BACKEND_HEALTH", "SIGNAL_COLD_START_LATENCY_SPIKE", "SIGNAL_CONFIG_DRIFT", "SIGNAL_DB_CPU", "SIGNAL_DISTRIBUTED_STRAGGLER", "SIGNAL_GATEWAY_LATENCY", "SIGNAL_GPU_ECC_UNCORRECTABLE", "SIGNAL_GPU_IDLE_HOURS_WASTED", "SIGNAL_GPU_PCIE_DEGRADATION", "SIGNAL_GPU_POWER_THROTTLE", "SIGNAL_GPU_SKU_MISMATCH", "SIGNAL_GPU_TEMP_THROTTLE", "SIGNAL_GPU_UTIL_SATURATED", "SIGNAL_GPU_UTIL_ZERO_WASTED", "SIGNAL_GPU_VRAM_OOM", "SIGNAL_GPU_XID_EVENT", "SIGNAL_HOST_CPU", "SIGNAL_HOST_MEMORY", "SIGNAL_INFERENCE_P99_SPIKE", "SIGNAL_KV_CACHE_PRESSURE", "SIGNAL_MEMBER_HOTSPOT", "SIGNAL_NCCL_TIMEOUT", "SIGNAL_NODE_CPU", "SIGNAL_POD_RESTART", "SIGNAL_RATE_LIMIT", "SIGNAL_REQUEST_FAILURE", "SIGNAL_ROLLOUT_STALL", "SIGNAL_SPOT_PREEMPT_CASCADE", "SIGNAL_TOKEN_SPEND_SPIKE", "SIGNAL_WEIGHTS_FETCH_STALL", "SignalRole", "SignalSpec", "is_known_signal", "known_signals", "signals_with_role"];
