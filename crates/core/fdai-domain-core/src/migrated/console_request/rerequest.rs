#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PriorRequestOutcome {
    #[default]
    None,
    NoOp,
    Denied,
}

impl PriorRequestOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::NoOp => "no_op",
            Self::Denied => "denied",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RerequestRefusal {
    #[default]
    DenyOverrideForbidden,
}

impl RerequestRefusal {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::DenyOverrideForbidden => "deny_override_forbidden",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RerequestDecision {
    pub allowed: bool,
    pub refusal: Option<RerequestRefusal>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn evaluate_operator_rerequest(mut prior_outcome: PriorRequestOutcome) -> RerequestDecision {
    RerequestDecision { allowed: true, ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PriorRequestOutcome", "RerequestDecision", "RerequestRefusal", "evaluate_operator_rerequest"];
