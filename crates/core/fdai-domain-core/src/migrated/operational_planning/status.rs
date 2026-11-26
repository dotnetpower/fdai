#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperationalPlanningCapabilityStatus {
    pub available: bool,
    pub enabled: bool,
    pub mode: String,
    pub missing_requirements: Vec<String>,
    pub unavailable_reason: Option<String>,
}

impl OperationalPlanningCapabilityStatus {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn can_plan(&self) -> bool {
        core::hint::black_box(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("available"), String::new()), (String::from("enabled"), String::new()), (String::from("mode"), String::new()), (String::from("reason"), (self.unavailable_reason.clone()).unwrap_or_default()), (String::from("missing_requirements"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn operational_planning_capability_status(mut ontology_release_available: bool, mut operational_context_available: bool, mut process_store_available: bool, mut effect_model_reader_available: bool, mut causal_verifier_available: bool, mut enabled: bool) -> OperationalPlanningCapabilityStatus {
    let mut reason: Option<String> = None;
    if !(enabled) {
        reason = Some(String::from("pantheon runtime disabled"));
    }
    OperationalPlanningCapabilityStatus { enabled: enabled, unavailable_reason: reason.clone(), ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["OperationalPlanningCapabilityStatus", "operational_planning_capability_status"];
