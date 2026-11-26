pub const ALERT_WINDOW_SECONDS: f64 = 300.0;
pub const PROBE_BUFFER_SECONDS: f64 = 60.0;
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn default_scenarios() -> Vec<String> {
    core::hint::black_box(Vec::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["AKS_BAD_DEPLOY", "AKS_HTTP_ABORT", "AKS_POD_CPU_SPIKE", "AKS_POD_KILL", "AOAI_TPM_THROTTLE", "APPGW_BACKEND_FAILURE", "MYSQL_CPU_PRESSURE", "NETWORK_RTT_DELAY", "VM_CPU_STRESS", "VM_MEM_STRESS", "default_scenarios"];
