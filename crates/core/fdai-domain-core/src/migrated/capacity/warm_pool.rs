#[derive(Clone, Debug, Default, PartialEq)]
pub struct WarmCapacityConfig {
    pub warm_at_or_above_severity: String,
    pub storm_forces_warm: bool,
    pub off_hours_forces_warm: bool,
    pub cold_min_replicas: i64,
    pub warm_min_replicas: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CapacityDecision {
    pub warm_required: bool,
    pub min_replicas: i64,
    pub triggers: Vec<String>,
    pub reason: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct WarmCapacityPolicy {
    pub initialized: bool,
}

impl WarmCapacityPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn decide(&self, mut severity: String, mut storm_active: bool, mut off_hours: bool) -> CapacityDecision {
        let mut triggers: Vec<String> = Vec::<String>::new();
        let warm_required: bool = !(triggers.clone()).is_empty();
        CapacityDecision { warm_required: warm_required, triggers: triggers.clone(), ..Default::default() }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["CapacityDecision", "WarmCapacityConfig", "WarmCapacityPolicy"];
