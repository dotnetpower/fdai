#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ControlSeverity {
    #[default]
    Critical,
    High,
    Medium,
    Low,
    Informational,
}

impl ControlSeverity {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Critical => "critical",
            Self::High => "high",
            Self::Medium => "medium",
            Self::Low => "low",
            Self::Informational => "informational",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ControlEnablement {
    pub severity: ControlSeverity,
    pub default_enabled: bool,
    pub enabled: bool,
    pub source: String,
}

impl ControlEnablement {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.source.as_str(), "severity_default" | "profile_override" | "lifecycle_disabled") { return Err("invalid source literal"); }
        Ok(())
    }
}

impl ControlEnablement {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("severity"), String::new()), (String::from("default_enabled"), String::new()), (String::from("enabled"), String::new()), (String::from("source"), self.source.clone()), (String::from("mode"), String::from("shadow")), (String::from("execution_authority"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn control_severity(mut value: String) -> ControlSeverity {
    let normalized: String = value.to_lowercase();
    Default::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn resolve_control_enablement(mut severity: String, mut enabled: Option<bool>, mut active: bool) -> Result<ControlEnablement, &'static str> {
    let priority: ControlSeverity = control_severity(severity.clone());
    Ok(ControlEnablement { severity: priority.clone(), source: if !(active) { String::from("lifecycle_disabled") } else { if enabled.is_some() { String::from("profile_override") } else { String::from("severity_default") } }, ..Default::default() })
}

