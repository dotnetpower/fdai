#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProviderFenceCapability {
    #[default]
    CommitFenceEnforced,
    IneligibleCapability,
}

impl ProviderFenceCapability {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::CommitFenceEnforced => "commit_fence_enforced",
            Self::IneligibleCapability => "ineligible_capability",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderEligibilityPartition {
    pub fence_capable: Vec<String>,
    pub ineligible: Vec<String>,
}

pub const A3E_COMMIT_FENCE_ADAPTERS: &[&str] = &[];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn a3e_fence_capability(mut action_type_id: String) -> Result<ProviderFenceCapability, &'static str> {
    if (!(true)) || ((action_type_id.trim().to_string()).is_empty()) {
        return Err("action_type_id MUST be non-empty text");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn partition_provider_eligibility(mut action_type_ids: Vec<String>) -> ProviderEligibilityPartition {
    let mut capable: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let mut ineligible: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    ProviderEligibilityPartition { fence_capable: (capable.clone()).into_iter().collect::<Vec<String>>(), ineligible: (ineligible.clone()).into_iter().collect::<Vec<String>>(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn derive_ineligible_provider_action_types(mut action_type_ids: Vec<String>) -> Vec<String> {
    (partition_provider_eligibility(action_type_ids.clone())).ineligible
}

pub const PUBLIC_EXPORTS: &[&str] = &["A3E_COMMIT_FENCE_ADAPTERS", "ProviderEligibilityPartition", "ProviderFenceCapability", "a3e_fence_capability", "derive_ineligible_provider_action_types", "partition_provider_eligibility"];
