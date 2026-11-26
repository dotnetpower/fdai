use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AccessObservationStatus {
    #[default]
    Allowed,
    Denied,
    Unknown,
}

impl AccessObservationStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Allowed => "allowed",
            Self::Denied => "denied",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AuthorizationRequirement {
    pub requirement_id: String,
    pub capability_id: String,
    pub action_type_ids: Vec<String>,
    pub resource_types: Vec<String>,
    pub scope_refs: Vec<String>,
    pub execution_profile: String,
    pub mapping_digest: String,
}

impl AuthorizationRequirement {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.requirement_id.trim().is_empty() { return Err("requirement_id must be non-empty"); }
        if self.capability_id.trim().is_empty() { return Err("capability_id must be non-empty"); }
        if self.execution_profile.trim().is_empty() { return Err("execution_profile must be non-empty"); }
        if self.mapping_digest.trim().is_empty() { return Err("mapping_digest must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AuthorizationObservation {
    pub observation_id: String,
    pub identity_ref: String,
    pub capability_id: String,
    pub scope_ref: String,
    pub mapping_digest: String,
    pub status: AccessObservationStatus,
    pub observed_at: String,
    pub expires_at: String,
    pub evidence_digest: String,
}

impl AuthorizationObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.observation_id.trim().is_empty() { return Err("observation_id must be non-empty"); }
        if self.identity_ref.trim().is_empty() { return Err("identity_ref must be non-empty"); }
        if self.capability_id.trim().is_empty() { return Err("capability_id must be non-empty"); }
        if self.scope_ref.trim().is_empty() { return Err("scope_ref must be non-empty"); }
        if self.mapping_digest.trim().is_empty() { return Err("mapping_digest must be non-empty"); }
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        if self.expires_at.trim().is_empty() { return Err("expires_at must be non-empty"); }
        if self.evidence_digest.trim().is_empty() { return Err("evidence_digest must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResolvedAuthorizationConstraints {
    pub allowed_grant_modes: Vec<String>,
    pub max_scope: String,
    pub max_duration_seconds: i64,
    pub quorum: i64,
    pub approver_roles: Vec<String>,
    pub required_evidence: Vec<String>,
    pub require_effective_probe: bool,
    pub exemptible: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AuthorizationDecision {
    pub status: String,
    pub action_type_id: String,
    pub capability_id: String,
    pub requirement_id: String,
    pub execution_profile: String,
    pub identity_ref: String,
    pub scope_refs: Vec<String>,
    pub assignment_ids: Vec<String>,
    pub observation_ids: Vec<String>,
    pub observation_evidence_digests: Vec<String>,
    pub reasons: Vec<String>,
    pub policy_bundle_digest: String,
    pub inventory_generation: String,
    pub algorithm_version: String,
    pub decision_digest: String,
    #[allow(clippy::type_complexity)]
    pub constraints: Option<Box<ResolvedAuthorizationConstraints>>,
    pub metadata: BTreeMap<String, String>,
}

impl AuthorizationRequirement {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn applies_to(&self, mut action_type_id: String, mut resource_type: String) -> bool {
        ((self.action_type_ids.clone()).contains(&(action_type_id.clone()))) && ((self.resource_types.clone()).contains(&(resource_type.clone())))
    }
}

impl AuthorizationDecision {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn can_enter_risk_gate(&self) -> bool {
        core::hint::black_box(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn as_audit_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("status"), String::new()), (String::from("action_type_id"), self.action_type_id.clone()), (String::from("capability_id"), self.capability_id.clone()), (String::from("requirement_id"), self.requirement_id.clone()), (String::from("execution_profile"), self.execution_profile.clone()), (String::from("identity_ref"), self.identity_ref.clone()), (String::from("scope_refs"), String::new()), (String::from("assignment_ids"), String::new()), (String::from("observation_ids"), String::new()), (String::from("observation_evidence_digests"), String::new()), (String::from("reasons"), String::new()), (String::from("policy_bundle_digest"), self.policy_bundle_digest.clone()), (String::from("inventory_generation"), self.inventory_generation.clone()), (String::from("algorithm_version"), self.algorithm_version.clone()), (String::from("decision_digest"), self.decision_digest.clone())])
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AccessObservationStatus", "AuthorizationConstraints", "AuthorizationDecision", "AuthorizationEnforcement", "AuthorizationObservation", "AuthorizationPolicyAssignment", "AuthorizationPosture", "AuthorizationRequirement", "AuthorizationScopeLevel", "AuthorizationStatus", "GrantMode", "ResolvedAuthorizationConstraints"];
