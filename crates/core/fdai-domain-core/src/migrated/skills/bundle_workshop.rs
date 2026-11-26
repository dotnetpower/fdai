#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SkillBundleProposalState {
    #[default]
    Draft,
    Approved,
    Rejected,
    Materialized,
}

impl SkillBundleProposalState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Draft => "draft",
            Self::Approved => "approved",
            Self::Rejected => "rejected",
            Self::Materialized => "materialized",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SkillBundleProposal {
    pub proposal_id: String,
    pub bundle_name: String,
    pub content_hash: String,
    pub manifest: Vec<u8>,
    pub proposed_by_agent: String,
    pub created_at: String,
    pub state: SkillBundleProposalState,
    pub reviewed_by: Option<String>,
    pub review_reason: Option<String>,
    pub reviewed_at: Option<String>,
}

pub trait SkillBundleProposalStore {
    fn create(&self, proposal: SkillBundleProposal) -> String;
}

pub trait SkillBundleWorkshopAudit {
    fn append(&self, event: std::collections::BTreeMap<String, String>) -> String;
}

pub trait SkillBundleReviewAuthorizer {
    fn can_review(&self, reviewer_id: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SkillBundleWorkshopError {
    pub message: String,
}

impl SkillBundleWorkshopError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for SkillBundleWorkshopError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SkillBundleWorkshopError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemorySkillBundleProposalStore {
    pub initialized: bool,
}

impl InMemorySkillBundleProposalStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn create(&self, mut proposal: SkillBundleProposal) -> Result<SkillBundleProposal, &'static str> {
        Ok(proposal.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get(&self, mut proposal_id: String) -> Result<SkillBundleProposal, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn transition(&self, mut proposal: SkillBundleProposal, mut expected_state: SkillBundleProposalState) -> Result<Option<SkillBundleProposal>, &'static str> {
        Ok(Some(proposal.clone()))
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SkillBundleWorkshop {
    pub initialized: bool,
}

impl SkillBundleWorkshop {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn propose(&self, mut raw_manifest: Vec<u8>, mut proposed_by_agent: String, mut at: String) -> Result<SkillBundleProposal, &'static str> {
        if (proposed_by_agent.clone()).is_empty() {
            return Err("skill bundle proposer agent MUST be non-empty");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn review(&self, mut proposal_id: String, mut reviewer_id: String, mut approve: bool, mut reason: String, mut at: String) -> Result<SkillBundleProposal, &'static str> {
        if ((reviewer_id.clone()).is_empty()) || (((reason.clone()).trim().to_string()).is_empty()) {
            return Err("skill bundle review requires reviewer and reason");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn materialize(&self, mut proposal_id: String, mut actor_id: String, mut at: String) -> Result<Vec<u8>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn promote(&self, mut proposal_id: String, mut actor_id: String, mut at: String, mut catalog: String, mut verifier: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn approved(&self, mut proposal_id: String, mut actor_id: String) -> Result<SkillBundleProposal, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn event(mut kind: String, mut proposal: SkillBundleProposal, mut actor: String, mut at: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("action_kind"), kind.clone()), (String::from("proposal_id"), proposal.proposal_id.clone()), (String::from("bundle_name"), proposal.bundle_name.clone()), (String::from("content_hash"), proposal.content_hash.clone()), (String::from("state"), String::new()), (String::from("actor"), actor.clone()), (String::from("timestamp"), String::new())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemorySkillBundleProposalStore", "SkillBundleProposal", "SkillBundleProposalState", "SkillBundleProposalStore", "SkillBundleWorkshop", "SkillBundleWorkshopError"];
