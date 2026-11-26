use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SLIKind {
    #[default]
    Availability,
    Latency,
    Correctness,
    Freshness,
}

impl SLIKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Availability => "availability",
            Self::Latency => "latency",
            Self::Correctness => "correctness",
            Self::Freshness => "freshness",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Sli {
    pub kind: SLIKind,
    pub good_query: String,
    pub total_query: String,
    pub labels: BTreeMap<String, String>,
}

impl Sli {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.good_query.trim().is_empty() { return Err("good_query must be non-empty"); }
        if self.total_query.trim().is_empty() { return Err("total_query must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BurnRateAlertDef {
    pub name: String,
    pub short_window_minutes: i64,
    pub long_window_minutes: i64,
    pub burn_rate_threshold: f64,
    pub severity: String,
}

impl BurnRateAlertDef {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.name.trim().is_empty() { return Err("name must be non-empty"); }
        if self.severity.trim().is_empty() { return Err("severity must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Slo {
    pub id: String,
    pub objective_ratio: f64,
    pub window_days: i64,
    pub sli: Box<Sli>,
    pub burn_rate_alerts: Vec<BurnRateAlertDef>,
    pub description: Option<String>,
    pub schema_version: String,
}

impl Slo {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.id.trim().is_empty() { return Err("id must be non-empty"); }
        if self.schema_version.trim().is_empty() { return Err("schema_version must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ErrorBudget {
    pub slo_id: String,
    pub good_events: i64,
    pub total_events: i64,
    pub objective_ratio: f64,
}

impl ErrorBudget {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.slo_id.trim().is_empty() { return Err("slo_id must be non-empty"); }
        Ok(())
    }
}

impl Slo {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn error_budget_fraction(&self) -> f64 {
        (1.0) - (self.objective_ratio)
    }
}

impl ErrorBudget {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn burned_events(&self) -> i64 {
        (self.total_events).saturating_sub(self.good_events)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_exhausted(&self) -> bool {
        core::hint::black_box(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn observed_ratio(&self) -> f64 {
        0.0_f64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn budget_remaining_fraction(&self) -> f64 {
        let actual_bad: i64 = (self.total_events).saturating_sub(self.good_events);
        0.0_f64
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["SLI", "SLO", "BurnRateAlertDef", "ErrorBudget", "SLIKind"];
