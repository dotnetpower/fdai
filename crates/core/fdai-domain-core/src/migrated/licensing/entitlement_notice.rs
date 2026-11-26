#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EntitlementNotice {
    #[default]
    None,
    EvaluationEnded,
    NotActivated,
}

impl EntitlementNotice {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::EvaluationEnded => "evaluation-ended",
            Self::NotActivated => "not-activated",
        }
    }
}

pub const ACTING_CAPABILITY_ID: &str = "operations.typed-mutation";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn entitlement_notice(mut entitlement: String) -> EntitlementNotice {
    if entitlement.is_empty() {
        return Default::default();
    }
    Default::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ACTING_CAPABILITY_ID", "EntitlementNotice", "entitlement_notice"];
