#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SkillProposalState {
    #[default]
    Draft,
    Approved,
    Rejected,
    Materialized,
}

impl SkillProposalState {
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
pub struct SkillProposal {
    pub proposal_id: String,
    pub skill_name: String,
    pub content_hash: String,
    pub markdown: Vec<u8>,
    pub proposed_by_agent: String,
    pub created_at: String,
    pub state: SkillProposalState,
    pub reviewed_by: Option<String>,
    pub review_reason: Option<String>,
    pub reviewed_at: Option<String>,
    pub evidence_refs: Vec<String>,
}

pub trait SkillProposalStore {
    fn create(&self, proposal: SkillProposal) -> String;
}

pub trait SkillWorkshopAudit {
    fn append(&self, event: std::collections::BTreeMap<String, String>) -> String;
}

pub trait SkillReviewAuthorizer {
    fn can_review(&self, reviewer_id: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SkillWorkshopError {
    pub message: String,
}

impl SkillWorkshopError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for SkillWorkshopError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SkillWorkshopError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemorySkillProposalStore {
    pub initialized: bool,
}

impl InMemorySkillProposalStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn create(&self, mut proposal: SkillProposal) -> Result<SkillProposal, &'static str> {
        Ok(proposal.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get(&self, mut proposal_id: String) -> Result<SkillProposal, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn transition(&self, mut proposal: SkillProposal, mut expected_state: SkillProposalState) -> Result<Option<SkillProposal>, &'static str> {
        Ok(Some(proposal.clone()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list(&self) -> Vec<SkillProposal> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SkillWorkshop {
    pub initialized: bool,
}

impl SkillWorkshop {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn propose_bundle(&self, mut raw_manifest: Vec<u8>, mut proposed_by_agent: String, mut at: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn review_bundle(&self, mut proposal_id: String, mut reviewer_id: String, mut approve: bool, mut reason: String, mut at: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn materialize_bundle(&self, mut proposal_id: String, mut actor_id: String, mut at: String) -> Vec<u8> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn promote_bundle(&self, mut proposal_id: String, mut actor_id: String, mut at: String, mut catalog: String, mut verifier: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn bundles(&self) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn propose(&self, mut raw_markdown: Vec<u8>, mut proposed_by_agent: String, mut at: String, mut evidence_refs: Vec<String>) -> Result<SkillProposal, &'static str> {
        if (proposed_by_agent.clone()).is_empty() {
            return Err("skill proposer agent MUST be non-empty");
        }
        let canonical_evidence: Vec<String> = ((evidence_refs.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).into_iter().collect::<Vec<String>>();
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn review(&self, mut proposal_id: String, mut reviewer_id: String, mut approve: bool, mut reason: String, mut at: String) -> Result<SkillProposal, &'static str> {
        if ((reviewer_id.clone()).is_empty()) || (((reason.clone()).trim().to_string()).is_empty()) {
            return Err("skill review requires reviewer and reason");
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
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn event(mut kind: String, mut proposal: SkillProposal, mut actor: String, mut at: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("action_kind"), kind.clone()), (String::from("proposal_id"), proposal.proposal_id.clone()), (String::from("skill_name"), proposal.skill_name.clone()), (String::from("content_hash"), proposal.content_hash.clone()), (String::from("evidence_refs"), String::new()), (String::from("state"), String::new()), (String::from("actor"), actor.clone()), (String::from("timestamp"), String::new())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemorySkillProposalStore", "SkillProposal", "SkillProposalState", "SkillProposalStore", "SkillReviewAuthorizer", "SkillWorkshop", "SkillWorkshopAudit", "SkillWorkshopError"];
