#[derive(Clone, Debug, Default, PartialEq)]
pub struct GpuSample {
    pub source: String,
    pub resource_ref: String,
    pub gpu_id: String,
    pub model: String,
    pub observed_at: String,
    pub utilization_pct: Option<f64>,
    pub memory_used_mib: Option<f64>,
    pub memory_total_mib: Option<f64>,
    pub temperature_c: Option<f64>,
    pub allocated: Option<bool>,
    pub queue_depth: Option<i64>,
    pub xid_code: Option<i64>,
    pub ecc_uncorrectable_total: Option<i64>,
    pub cuda_oom_total: Option<i64>,
    pub thermal_throttled: Option<bool>,
}

impl GpuSample {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.source.as_str(), "azure_monitor" | "datadog" | "azure_vm_run_command") { return Err("invalid source literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Policy {
    pub window_seconds: i64,
    pub max_gap_seconds: i64,
    pub max_age_seconds: i64,
    pub max_samples: i64,
    pub saturation_pct: f64,
    pub idle_utilization_pct: f64,
    pub memory_pressure_pct: f64,
    pub temperature_c: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Analysis {
    pub status: String,
    pub reason: String,
    pub samples: Vec<GpuSample>,
    pub events: Vec<String>,
    pub evidence_digest: Option<String>,
    pub policy_digest: Option<String>,
    pub evidence_origin: String,
}

impl Analysis {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.status.as_str(), "healthy" | "finding" | "insufficient_evidence") { return Err("invalid status literal"); }
        if !matches!(self.evidence_origin.as_str(), "synthetic_replay" | "authenticated_live_observation") { return Err("invalid evidence_origin literal"); }
        Ok(())
    }
}

impl GpuSample {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_time(mut value: String) -> Result<String, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_observation(&self) -> Result<String, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn identity(&self) -> (String, String, String, String) {
        (self.source.clone(), self.resource_ref.clone(), self.gpu_id.clone(), self.model.clone())
    }
}

