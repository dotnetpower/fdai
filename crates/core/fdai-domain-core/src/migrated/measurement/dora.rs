#[derive(Clone, Debug, Default, PartialEq)]
pub struct DeploymentObservation {
    pub deployment_id: String,
    pub committed_at: String,
    pub deployed_at: String,
    pub failed: bool,
    pub recovered_at: Option<String>,
}

impl DeploymentObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.deployment_id.trim().is_empty() { return Err("deployment_id must be non-empty"); }
        if self.committed_at.trim().is_empty() { return Err("committed_at must be non-empty"); }
        if self.deployed_at.trim().is_empty() { return Err("deployed_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DoraSummary {
    pub window_days: f64,
    pub deployment_count: i64,
    pub failed_count: i64,
    pub unrecovered_failure_count: i64,
    pub invalid_count: i64,
    pub deployment_frequency_per_day: f64,
    pub change_failure_rate: Option<f64>,
    pub lead_time_mean_seconds: Option<f64>,
    pub lead_time_median_seconds: Option<f64>,
    pub lead_time_p90_seconds: Option<f64>,
    pub failed_change_recovery_mean_seconds: Option<f64>,
    pub failed_change_recovery_median_seconds: Option<f64>,
    pub failed_change_recovery_p90_seconds: Option<f64>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn compute_dora(mut deployments: Vec<DeploymentObservation>, mut window_start: String, mut window_end: String) -> Result<DoraSummary, &'static str> {
    let mut included: i64 = 0_i64;
    let mut failed: i64 = 0_i64;
    let mut unrecovered: i64 = 0_i64;
    let mut invalid: i64 = 0_i64;
    let mut lead_times: Vec<f64> = Vec::<f64>::new();
    let mut recovery_times: Vec<f64> = Vec::<f64>::new();
    let mut seen: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    for deployment in deployments.clone() {
        if (seen.clone()).contains((deployment.deployment_id.clone()).as_str()) {
            continue;
        }
        seen.insert(deployment.deployment_id.clone());
        if !(((window_start.clone()) <= (deployment.deployed_at.clone())) && ((deployment.deployed_at.clone()) <= (window_end.clone()))) {
            continue;
        }
        if ((deployment.recovered_at.clone()).is_some()) && (((deployment.recovered_at.clone()).unwrap_or_default()) < (deployment.deployed_at.clone())) {
            invalid = invalid.saturating_add(1_i64);
            continue;
        }
        included = included.saturating_add(1_i64);
        if deployment.failed {
            failed = failed.saturating_add(1_i64);
            if (deployment.recovered_at.clone()).is_none() {
                unrecovered = unrecovered.saturating_add(1_i64);
            }
        }
    }
    let lead_stats: (Option<f64>, Option<f64>, Option<f64>) = distribution(lead_times.clone());
    let recovery_stats: (Option<f64>, Option<f64>, Option<f64>) = distribution(recovery_times.clone());
    Ok(DoraSummary { deployment_count: included, failed_count: failed, unrecovered_failure_count: unrecovered, invalid_count: invalid, ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn distribution(mut values: Vec<f64>) -> (Option<f64>, Option<f64>, Option<f64>) {
    if (values.clone()).is_empty() {
        return (None, None, None);
    }
    (None, None, None)
}

pub const PUBLIC_EXPORTS: &[&str] = &["DeploymentObservation", "DoraSummary", "compute_dora"];
