use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct HandoverReadinessReport {
    pub schema_version: String,
    pub revision: i64,
    pub observed_at: String,
    pub expires_at: String,
    pub mode: String,
    pub execution_authority: bool,
    pub operationally_ready: bool,
    pub enabled: bool,
    pub sample_limit: i64,
    pub cases_observed: i64,
    pub cases_total: i64,
    pub cases_invalid: i64,
    pub cases_by_state: BTreeMap<String, i64>,
    pub knowledge_observed: i64,
    pub knowledge_total: i64,
    pub knowledge_invalid: i64,
    pub knowledge_by_disposition: BTreeMap<String, i64>,
    pub partial: bool,
    pub convergence_samples: i64,
    pub mean_effect_interval_seconds: Option<f64>,
    pub alerts: Vec<String>,
    pub source_gaps: Vec<String>,
    pub external_blockers: Vec<String>,
}

impl HandoverReadinessReport {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        if self.expires_at.trim().is_empty() { return Err("expires_at must be non-empty"); }
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.revision) { return Err("revision out of bounds"); }
        if !matches!(self.mode.as_str(), "shadow") { return Err("invalid mode literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.operationally_ready { return Err("operationally_ready violated literal bool invariant"); }
        if !(1_i64..=1000_i64).contains(&self.sample_limit) { return Err("sample_limit out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.cases_observed) { return Err("cases_observed out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.cases_total) { return Err("cases_total out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.cases_invalid) { return Err("cases_invalid out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.knowledge_observed) { return Err("knowledge_observed out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.knowledge_total) { return Err("knowledge_total out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.knowledge_invalid) { return Err("knowledge_invalid out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.convergence_samples) { return Err("convergence_samples out of bounds"); }
        Ok(())
    }
}

pub const HANDOVER_READINESS_KEY: &str = "human_assignment:readiness:current";
impl HandoverReadinessReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn bounded_snapshot(&self) -> Result<HandoverReadinessReport, &'static str> {
        if (self.partial) != (((self.cases_observed) < (self.cases_total)) || ((self.knowledge_observed) < (self.knowledge_total))) {
            return Err("handover readiness partial state does not match source totals");
        }
        if ((self.convergence_samples) == (0_i64)) != (self.mean_effect_interval_seconds.is_none()) {
            return Err("missing convergence samples MUST report an unavailable mean");
        }
        if (self.convergence_samples) > ((self.cases_observed).saturating_sub(self.cases_invalid)) {
            return Err("convergence samples exceed verified case observations");
        }
        Ok(self.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn require_current(&self, mut now: String) -> Result<(), &'static str> {
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["HANDOVER_READINESS_KEY", "HandoverReadinessReport"];
