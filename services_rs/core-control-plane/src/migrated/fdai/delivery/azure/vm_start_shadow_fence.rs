#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureVmStartShadowFenceBinding {
    pub resource_ref: String,
    pub resource_group: String,
    pub vm_name: String,
    pub action_digest: String,
    pub target_digest: String,
    pub executor_identity: String,
    pub source_revision_id: String,
    pub action_type_name: String,
    pub action_type_version: String,
    pub resource_group_count: i64,
    pub resource_count: i64,
}

impl AzureVmStartShadowFenceBinding {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.action_type_name.as_str(), "ops.start-vm") { return Err("invalid action_type_name literal"); }
        if !matches!(self.action_type_version.as_str(), "1.0.0") { return Err("invalid action_type_version literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderFenceShadowReceipt {
    pub action_type_name: String,
    pub action_type_version: String,
    pub resource_ref: String,
    pub resource_group: String,
    pub vm_name: String,
    pub lease_id: String,
    pub family_id: String,
    pub authorization_revision_id: String,
    pub lease_generation: i64,
    pub fencing_generation: i64,
    pub transition_digest: String,
    pub action_digest: String,
    pub target_digest: String,
    pub executor_identity: String,
    pub source_revision_id: String,
    pub observed_at: String,
    pub fence_outcome: String,
    pub fence_current: bool,
    pub complete: bool,
    pub provider_capability_outcome: String,
    pub provider_commit_attempted: bool,
    pub effect_applied: bool,
    pub effect_verified: bool,
    pub execution_authority: bool,
    pub promotion_authority: bool,
    pub receipt_id: String,
}

impl ProviderFenceShadowReceipt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.provider_commit_attempted { return Err("provider_commit_attempted violated literal bool invariant"); }
        if self.effect_applied { return Err("effect_applied violated literal bool invariant"); }
        if self.effect_verified { return Err("effect_verified violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.promotion_authority { return Err("promotion_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub const ACTION_TYPE: &str = "ops.start-vm";
pub const ACTION_TYPE_VERSION: &str = "1.0.0";
pub const NAME: &str = "^[A-Za-z0-9][A-Za-z0-9_.()-]{0,127}$";
pub const REVISION: &str = "^(?:[0-9a-f]{40}|[0-9a-f]{64})$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureVmStartShadowFenceProbe {
    pub initialized: bool,
}

impl AzureVmStartShadowFenceProbe {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn probe(&self, mut binding: AzureVmStartShadowFenceBinding, mut lease: String, mut observed_at: String) -> ProviderFenceShadowReceipt {
        let _ = validate_lease(binding.clone(), lease.clone()).unwrap_or_else(|_| ());
        ProviderFenceShadowReceipt { action_type_name: binding.action_type_name.clone(), action_type_version: binding.action_type_version.clone(), resource_ref: (binding.resource_ref.clone()).to_lowercase(), resource_group: (binding.resource_group.clone()).to_lowercase(), vm_name: (binding.vm_name.clone()).to_lowercase(), source_revision_id: binding.source_revision_id.clone(), observed_at: observed_at.clone(), ..Default::default() }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_azure_vm_start_shadow_binding(mut resource_ref: String, mut resource_group: String, mut vm_name: String, mut action_digest: String, mut executor_identity: String, mut source_revision_id: String) -> AzureVmStartShadowFenceBinding {
    AzureVmStartShadowFenceBinding { resource_ref: resource_ref.clone(), resource_group: resource_group.clone(), vm_name: vm_name.clone(), action_digest: action_digest.clone(), target_digest: azure_vm_target_digest(resource_ref.clone()).unwrap_or_else(|_| String::new()), executor_identity: executor_identity.clone(), source_revision_id: source_revision_id.clone(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn azure_vm_target_digest(mut resource_ref: String) -> Result<String, &'static str> {
    if resource_ref.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_lease(mut binding: AzureVmStartShadowFenceBinding, mut lease: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_canonical_subscription(mut subscription: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn receipt_body(mut receipt: ProviderFenceShadowReceipt) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("action_type_name"), receipt.action_type_name.clone()), (String::from("action_type_version"), receipt.action_type_version.clone()), (String::from("resource_ref"), receipt.resource_ref.clone()), (String::from("resource_group"), receipt.resource_group.clone()), (String::from("vm_name"), receipt.vm_name.clone()), (String::from("lease_id"), receipt.lease_id.clone()), (String::from("family_id"), receipt.family_id.clone()), (String::from("authorization_revision_id"), receipt.authorization_revision_id.clone()), (String::from("lease_generation"), String::new()), (String::from("fencing_generation"), String::new()), (String::from("transition_digest"), receipt.transition_digest.clone()), (String::from("action_digest"), receipt.action_digest.clone()), (String::from("target_digest"), receipt.target_digest.clone()), (String::from("executor_identity"), receipt.executor_identity.clone()), (String::from("source_revision_id"), receipt.source_revision_id.clone()), (String::from("observed_at"), String::new()), (String::from("fence_outcome"), String::new()), (String::from("fence_current"), String::new()), (String::from("complete"), String::new()), (String::from("provider_capability_outcome"), String::new()), (String::from("provider_commit_attempted"), String::new()), (String::from("effect_applied"), String::new()), (String::from("effect_verified"), String::new()), (String::from("execution_authority"), String::new()), (String::from("promotion_authority"), String::new())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureVmStartShadowFenceBinding", "AzureVmStartShadowFenceProbe", "ProviderFenceShadowReceipt", "azure_vm_target_digest", "build_azure_vm_start_shadow_binding"];
