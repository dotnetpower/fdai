use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OverrideMode {
    #[default]
    Disabled,
    SeverityDowngrade,
    ParameterRelaxation,
}

impl OverrideMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Disabled => "disabled",
            Self::SeverityDowngrade => "severity-downgrade",
            Self::ParameterRelaxation => "parameter-relaxation",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Override {
    pub id: String,
    pub target_rule: String,
    pub scope: String,
    pub mode: OverrideMode,
    pub justification: String,
    pub requested_by: String,
    pub approver: String,
    pub severity_downgrade_to: Option<String>,
    pub parameter_overrides: BTreeMap<String, String>,
    pub expires_at: Option<String>,
    pub provenance: Option<String>,
    pub version: Option<String>,
}

impl Override {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.id.trim().is_empty() { return Err("id must be non-empty"); }
        if self.target_rule.trim().is_empty() { return Err("target_rule must be non-empty"); }
        if self.scope.trim().is_empty() { return Err("scope must be non-empty"); }
        if self.justification.trim().is_empty() { return Err("justification must be non-empty"); }
        if self.requested_by.trim().is_empty() { return Err("requested_by must be non-empty"); }
        if self.approver.trim().is_empty() { return Err("approver must be non-empty"); }
        Ok(())
    }
}

impl Override {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn covers(&self, mut ctx: String, mut at: String) -> Result<bool, &'static str> {
        if (self.expires_at.is_some()) && (((self.expires_at.clone()).unwrap_or_default()) <= (at.clone())) {
            return Ok(false);
        }
        Ok(false)
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resolve_override(mut overrides: Vec<Override>, mut ctx: String, mut rule_id: String, mut at: String) -> Option<Override> {
    if overrides.is_empty() {
        return None;
    }
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["Override", "OverrideMode", "resolve_override"];
