use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct AvailabilityPlannedStopSettings {
    pub since: String,
    pub until: String,
    pub reference: String,
    pub maintenance: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AvailabilityResourcePolicySettings {
    pub resource_type: String,
    pub reference: String,
    pub expected_state: Option<String>,
    pub planned_stops: Vec<AvailabilityPlannedStopSettings>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResourceAvailabilitySettings {
    pub enabled: String,
    pub resource_types: Vec<String>,
    pub max_age_seconds: f64,
    pub resources: BTreeMap<String, AvailabilityResourcePolicySettings>,
}

impl ResourceAvailabilitySettings {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.enabled.trim().is_empty() { return Err("enabled must be non-empty"); }
        Ok(())
    }
}

pub const RESOURCE_AVAILABILITY_SETTING_KEY: &str = "detection.resource_availability";
impl AvailabilityPlannedStopSettings {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn ordered(&self) -> Result<AvailabilityPlannedStopSettings, &'static str> {
        if (self.since.clone()) >= (self.until.clone()) {
            return Err("planned stop window MUST be positive");
        }
        Ok(self.clone())
    }
}

impl ResourceAvailabilitySettings {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn explicit_scope(&self) -> Result<ResourceAvailabilitySettings, &'static str> {
        let selected: std::collections::BTreeSet<String> = (self.resource_types.clone()).into_iter().collect::<std::collections::BTreeSet<String>>();
        Ok(self.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_resource_availability_setting(mut value: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

