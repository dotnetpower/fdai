#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum IamCapability {
    #[default]
    ViewConsole,
    AuthorDraftPr,
    ApproveRuntimeHil,
    TriggerKillSwitch,
    ActivateBreakGlass,
    ManageRuntimeSettings,
    ViewIntegrationSecrets,
    ManageModelBindings,
    ManageGroupMembership,
}

impl IamCapability {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ViewConsole => "view-console",
            Self::AuthorDraftPr => "author-draft-pr",
            Self::ApproveRuntimeHil => "approve-runtime-hil",
            Self::TriggerKillSwitch => "trigger-kill-switch",
            Self::ActivateBreakGlass => "activate-break-glass",
            Self::ManageRuntimeSettings => "manage-runtime-settings",
            Self::ViewIntegrationSecrets => "view-integration-secrets",
            Self::ManageModelBindings => "manage-model-bindings",
            Self::ManageGroupMembership => "manage-group-membership",
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn capabilities_for(mut roles: Vec<String>) -> std::collections::BTreeSet<IamCapability> {
    let capabilities: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    std::collections::BTreeSet::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn has_capability(mut roles: Vec<String>, mut capability: IamCapability) -> bool {
    if roles.is_empty() {
        return false;
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["IamCapability", "ROLE_CAPABILITIES", "capabilities_for", "has_capability"];
