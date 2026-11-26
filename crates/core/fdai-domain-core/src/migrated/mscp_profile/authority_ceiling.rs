#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MscpAuthorityCeiling {
    #[default]
    Preserve,
    HumanApproval,
    Hold,
    Deny,
}

impl MscpAuthorityCeiling {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Preserve => "preserve",
            Self::HumanApproval => "human_approval",
            Self::Hold => "hold",
            Self::Deny => "deny",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MscpAuthorityReason {
    #[default]
    NotApplicable,
    ChecksPassed,
    HumanReviewRequired,
    StructuralHold,
    PolicyDeny,
}

impl MscpAuthorityReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::NotApplicable => "not_applicable",
            Self::ChecksPassed => "checks_passed",
            Self::HumanReviewRequired => "human_review_required",
            Self::StructuralHold => "structural_hold",
            Self::PolicyDeny => "policy_deny",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MscpAuthorityDecision {
    pub existing: String,
    pub ceiling: MscpAuthorityCeiling,
    pub reason: MscpAuthorityReason,
    pub level: String,
}

impl MscpAuthorityDecision {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn decision(&self) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn lowered(&self) -> bool {
        core::hint::black_box(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn as_audit_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("safety_profile"), String::new()), (String::from("existing_decision"), String::new()), (String::from("ceiling"), String::new()), (String::from("reason"), String::new()), (String::from("decision"), String::new()), (String::from("lowered"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn combine_mscp_authority(mut existing: String, mut ceiling: MscpAuthorityCeiling, mut reason: MscpAuthorityReason) -> MscpAuthorityDecision {
    MscpAuthorityDecision { existing: existing.clone(), ceiling: ceiling.clone(), reason: reason.clone(), ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["MscpAuthorityCeiling", "MscpAuthorityDecision", "MscpAuthorityReason", "combine_mscp_authority"];
