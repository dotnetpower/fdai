#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ChangeRisk {
    #[default]
    Low,
    High,
}

impl ChangeRisk {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Low => "low",
            Self::High => "high",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ChangeDecisionOutcome {
    #[default]
    Auto,
    Hil,
    Reject,
    Timeout,
}

impl ChangeDecisionOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Auto => "auto",
            Self::Hil => "hil",
            Self::Reject => "reject",
            Self::Timeout => "timeout",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChangeContext {
    pub change_id: String,
    pub resource_id: String,
    pub is_reversible: bool,
    pub is_out_of_band: bool,
    pub target_environment: String,
}

impl ChangeContext {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.change_id.trim().is_empty() { return Err("change_id must be non-empty"); }
        if self.resource_id.trim().is_empty() { return Err("resource_id must be non-empty"); }
        if self.target_environment.trim().is_empty() { return Err("target_environment must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChangeDecision {
    pub change_id: String,
    pub risk: ChangeRisk,
    pub outcome: ChangeDecisionOutcome,
    pub reasons: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChangeSafetyConfig {
    pub production_environments: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ChangeSafetyClassifier {
    pub initialized: bool,
}

impl ChangeSafetyClassifier {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn classify(&self, mut context: ChangeContext) -> ChangeDecision {
        let mut reasons: Vec<String> = Vec::<String>::new();
        if context.is_out_of_band {
            reasons.push(String::from("out_of_band_change"));
        }
        if !(context.is_reversible) {
            reasons.push(String::from("irreversible_change"));
        }
        if !(reasons.clone()).is_empty() {
            return ChangeDecision { change_id: context.change_id.clone(), reasons: reasons.clone(), ..Default::default() };
        }
        ChangeDecision { change_id: context.change_id.clone(), ..Default::default() }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn record_terminal(&self, mut change_id: String, mut outcome: ChangeDecisionOutcome, mut reason: String) -> Result<ChangeDecision, &'static str> {
        if ((change_id.trim().to_string()).is_empty()) || (((reason.clone()).trim().to_string()).is_empty()) {
            return Err("record_terminal change_id and reason MUST be non-empty");
        }
        Ok(ChangeDecision { change_id: change_id.clone(), outcome: outcome.clone(), ..Default::default() })
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ChangeContext", "ChangeDecision", "ChangeDecisionOutcome", "ChangeRisk", "ChangeSafetyClassifier", "ChangeSafetyConfig"];
