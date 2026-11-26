#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum KnowledgeEvidenceEventType {
    #[default]
    Proposed,
    Duplicate,
    Conflict,
    OntologyCandidate,
    RuleCandidate,
}

impl KnowledgeEvidenceEventType {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Proposed => "knowledge.evidence.proposed",
            Self::Duplicate => "knowledge.evidence.duplicate",
            Self::Conflict => "knowledge.evidence.conflict",
            Self::OntologyCandidate => "knowledge.ontology-candidate.proposed",
            Self::RuleCandidate => "knowledge.rule-candidate.proposed",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct KnowledgeEvidenceEvent {
    pub event_type: KnowledgeEvidenceEventType,
    pub goal_ref: String,
    pub evidence_refs: Vec<String>,
    pub evidence_digest: String,
    pub producer_agent: String,
    pub reason_code: String,
    pub content_included: bool,
    pub requires_review: bool,
}

impl KnowledgeEvidenceEvent {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.content_included { return Err("content_included violated literal bool invariant"); }
        if !self.requires_review { return Err("requires_review violated literal bool invariant"); }
        Ok(())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["KnowledgeEvidenceEvent", "KnowledgeEvidenceEventType"];
