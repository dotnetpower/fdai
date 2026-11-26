#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RetirementMode {
    #[default]
    ShadowOnly,
    Retired,
}

impl RetirementMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ShadowOnly => "shadow_only",
            Self::Retired => "retired",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleRetirement {
    pub schema_version: String,
    pub rule_id: String,
    pub mode: RetirementMode,
    pub justification: String,
    pub requested_by: String,
    pub approved_by: String,
    pub decided_at: String,
}

impl RuleRetirement {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_distinct_principals(&self) -> Result<RuleRetirement, &'static str> {
        if (self.requested_by.clone()) == (self.approved_by.clone()) {
            return Err("requested_by MUST differ from approved_by");
        }
        Ok(self.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn load_retirement_from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> RuleRetirement {
    if raw.is_empty() {
        return Default::default();
    }
    Default::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["RetirementMode", "RuleRetirement", "load_retirement_from_mapping"];
