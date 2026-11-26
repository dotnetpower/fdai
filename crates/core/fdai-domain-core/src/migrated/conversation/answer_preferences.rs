use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResponsePreferenceProfile {
    pub locale: String,
    pub default_detail: String,
    pub default_format: String,
    pub intent_detail: BTreeMap<String, String>,
    pub intent_format: BTreeMap<String, String>,
    pub explicit_only: bool,
    pub updated_at: String,
}

impl ResponsePreferenceProfile {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.locale.trim().is_empty() { return Err("locale must be non-empty"); }
        if self.default_detail.trim().is_empty() { return Err("default_detail must be non-empty"); }
        if self.default_format.trim().is_empty() { return Err("default_format must be non-empty"); }
        if self.updated_at.trim().is_empty() { return Err("updated_at must be non-empty"); }
        Ok(())
    }
}

impl ResponsePreferenceProfile {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn detail_for(&self, mut intent: String) -> Option<String> {
        if self.explicit_only {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn format_for(&self, mut intent: String) -> Option<String> {
        if self.explicit_only {
            return None;
        }
        None
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ResponsePreferenceProfile"];
