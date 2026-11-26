#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Role {
    #[default]
    Reader,
    Contributor,
    Approver,
    Owner,
    BreakGlass,
}

impl Role {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Reader => "Reader",
            Self::Contributor => "Contributor",
            Self::Approver => "Approver",
            Self::Owner => "Owner",
            Self::BreakGlass => "BreakGlass",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Capability {
    #[default]
    ViewConsole,
    AuthorDraftPr,
    StartReadInvestigation,
    ReviewGovernancePr,
    ApproveQuorumPromotion,
    ApproveExemption,
    ApproveOverride,
    ApproveRuntimeHil,
    TriggerKillSwitch,
    GrantEmergencyAccess,
    ManageRuntimeSettings,
    ManageGroupMembership,
    ApplyInfraIac,
}

impl Capability {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ViewConsole => "view-console",
            Self::AuthorDraftPr => "author-draft-pr",
            Self::StartReadInvestigation => "start-read-investigation",
            Self::ReviewGovernancePr => "review-governance-pr",
            Self::ApproveQuorumPromotion => "approve-quorum-promotion",
            Self::ApproveExemption => "approve-exemption",
            Self::ApproveOverride => "approve-override",
            Self::ApproveRuntimeHil => "approve-runtime-hil",
            Self::TriggerKillSwitch => "trigger-kill-switch",
            Self::GrantEmergencyAccess => "grant-emergency-access",
            Self::ManageRuntimeSettings => "manage-runtime-settings",
            Self::ManageGroupMembership => "manage-group-membership",
            Self::ApplyInfraIac => "apply-infra-iac",
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn capabilities_for(mut roles: Vec<Role>) -> std::collections::BTreeSet<Capability> {
    let mut acc: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    std::collections::BTreeSet::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn has_capability(mut roles: Vec<Role>, mut capability: Capability) -> bool {
    if roles.is_empty() {
        return false;
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["ROLE_CAPABILITIES", "Capability", "Role", "capabilities_for", "has_capability"];
