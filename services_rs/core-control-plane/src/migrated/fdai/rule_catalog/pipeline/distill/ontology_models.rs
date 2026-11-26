pub const MAX_PROPERTY_STRING: i64 = 4096;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ClaimKind {
    #[default]
    Unclassified,
    Normative,
    Threshold,
    Entity,
    Relationship,
    Procedure,
    Observation,
    History,
}

impl ClaimKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Unclassified => "unclassified",
            Self::Normative => "normative",
            Self::Threshold => "threshold",
            Self::Entity => "entity",
            Self::Relationship => "relationship",
            Self::Procedure => "procedure",
            Self::Observation => "observation",
            Self::History => "history",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AuthorityClass {
    #[default]
    Unclassified,
    DeclaredIntent,
    Procedure,
    HistoricalEvidence,
    ProviderObservation,
    TelemetryObservation,
    ExecutionAuthority,
}

impl AuthorityClass {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Unclassified => "unclassified",
            Self::DeclaredIntent => "declared_intent",
            Self::Procedure => "procedure",
            Self::HistoricalEvidence => "historical_evidence",
            Self::ProviderObservation => "provider_observation",
            Self::TelemetryObservation => "telemetry_observation",
            Self::ExecutionAuthority => "execution_authority",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ClaimDisposition {
    #[default]
    Mapped,
    IgnoredWithReason,
    NeedsReview,
}

impl ClaimDisposition {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Mapped => "mapped",
            Self::IgnoredWithReason => "ignored_with_reason",
            Self::NeedsReview => "needs_review",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OntologyOperation {
    #[default]
    Add,
    Update,
    Remove,
    Supersede,
}

impl OntologyOperation {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Add => "add",
            Self::Update => "update",
            Self::Remove => "remove",
            Self::Supersede => "supersede",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OntologyTargetKind {
    #[default]
    Object,
    Link,
}

impl OntologyTargetKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Object => "object",
            Self::Link => "link",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProposalState {
    #[default]
    Candidate,
    Validated,
    ReviewRequired,
    Approved,
    Projected,
    Reconciled,
    Denied,
    Rejected,
    Superseded,
    RolledBack,
}

impl ProposalState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Candidate => "candidate",
            Self::Validated => "validated",
            Self::ReviewRequired => "review_required",
            Self::Approved => "approved",
            Self::Projected => "projected",
            Self::Reconciled => "reconciled",
            Self::Denied => "denied",
            Self::Rejected => "rejected",
            Self::Superseded => "superseded",
            Self::RolledBack => "rolled_back",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum GateOutcome {
    #[default]
    Pass,
    Review,
    Deny,
}

impl GateOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pass => "pass",
            Self::Review => "review",
            Self::Deny => "deny",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SourceEvidence {
    pub source_ref: String,
    pub document_id: String,
    pub document_revision: String,
    pub content_sha256: String,
    pub line_start: i64,
    pub line_end: i64,
    pub text_sha256: String,
    pub source_format: String,
    pub structural_unit_id: String,
    pub structural_locator: String,
}

impl SourceEvidence {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.source_ref.trim().is_empty() { return Err("source_ref must be non-empty"); }
        if self.document_id.trim().is_empty() { return Err("document_id must be non-empty"); }
        if self.document_revision.trim().is_empty() { return Err("document_revision must be non-empty"); }
        if self.content_sha256.trim().is_empty() { return Err("content_sha256 must be non-empty"); }
        if self.text_sha256.trim().is_empty() { return Err("text_sha256 must be non-empty"); }
        if self.source_format.trim().is_empty() { return Err("source_format must be non-empty"); }
        if self.structural_unit_id.trim().is_empty() { return Err("structural_unit_id must be non-empty"); }
        if self.structural_locator.trim().is_empty() { return Err("structural_locator must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ClaimUnit {
    pub claim_id: String,
    pub kind: ClaimKind,
    pub authority: AuthorityClass,
    pub evidence: Box<SourceEvidence>,
    pub critical: bool,
    pub signals: Vec<ClaimKind>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ClaimResolution {
    pub claim_id: String,
    pub disposition: ClaimDisposition,
    pub candidate_ids: Vec<String>,
    pub reason_code: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyProperty {
    pub name: String,
    pub value: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EntityResolution {
    pub selected_identity: Option<String>,
    pub candidates: Vec<String>,
    pub method: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyChangeProposal {
    pub proposal_id: String,
    pub extraction_run_id: String,
    pub candidate_id: String,
    pub claim_id: String,
    pub operation: OntologyOperation,
    pub target_kind: OntologyTargetKind,
    pub target_type: String,
    pub target_identity: String,
    pub ontology_release: String,
    pub expected_graph_revision: String,
    pub authority: AuthorityClass,
    pub evidence: Box<SourceEvidence>,
    pub entity_resolution: Box<EntityResolution>,
    pub properties: Vec<OntologyProperty>,
    pub from_identity: Option<String>,
    pub to_identity: Option<String>,
    #[allow(clippy::type_complexity)]
    pub from_resolution: Option<Box<EntityResolution>>,
    #[allow(clippy::type_complexity)]
    pub to_resolution: Option<Box<EntityResolution>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct GateReceipt {
    pub gate: String,
    pub outcome: GateOutcome,
    pub reason_codes: Vec<String>,
    pub evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerifiedOntologyProposal {
    pub proposal: Box<OntologyChangeProposal>,
    pub state: ProposalState,
    pub receipts: Vec<GateReceipt>,
}

pub const DIGEST: &str = "^[a-f0-9]{64}$";
pub const IDENTIFIER: &str = "^[A-Za-z][A-Za-z0-9_.:-]{0,199}$";
pub const PROPERTY: &str = "^[a-z][a-z0-9_]{0,63}$";
impl OntologyChangeProposal {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        stable_digest(String::new())
    }
}

impl VerifiedOntologyProposal {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn verification_digest(&self) -> String {
        stable_digest(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn stable_digest(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn proposal_payload(mut proposal: OntologyChangeProposal) -> std::collections::BTreeMap<String, String> {
    let mut payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("proposal_id"), proposal.proposal_id.clone()), (String::from("extraction_run_id"), proposal.extraction_run_id.clone()), (String::from("candidate_id"), proposal.candidate_id.clone()), (String::from("claim_id"), proposal.claim_id.clone()), (String::from("operation"), String::new()), (String::from("target_kind"), String::new()), (String::from("target_type"), proposal.target_type.clone()), (String::from("target_identity"), proposal.target_identity.clone()), (String::from("ontology_release"), proposal.ontology_release.clone()), (String::from("expected_graph_revision"), proposal.expected_graph_revision.clone()), (String::from("authority"), String::new()), (String::from("evidence"), String::new()), (String::from("entity_resolution"), String::new()), (String::from("properties"), String::new()), (String::from("from_identity"), (proposal.from_identity.clone()).unwrap_or_default()), (String::from("to_identity"), (proposal.to_identity.clone()).unwrap_or_default())]);
    payload.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_digest(mut value: String, mut field_name: String) -> Result<(), &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_identifier(mut value: String, mut field_name: String) -> Result<(), &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_unresolved_reference(mut value: String, mut field_name: String) -> Result<(), &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_endpoint_resolution(mut identity: String, mut resolution: EntityResolution, mut field_name: String) -> Result<(), &'static str> {
    if (resolution.selected_identity.clone()).is_none() {
        let _ = require_unresolved_reference(identity.clone(), field_name.clone()).unwrap_or_else(|_| ());
    } else if (identity.clone()) != ((resolution.selected_identity.clone()).unwrap_or_default()) {
        return Err("field_name MUST match its selected endpoint identity");
    } else {
        let _ = require_identifier(identity.clone(), field_name.clone()).unwrap_or_else(|_| ());
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resolution_payload(mut resolution: EntityResolution) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("selected_identity"), (resolution.selected_identity.clone()).unwrap_or_default()), (String::from("candidates"), String::new()), (String::from("method"), resolution.method.clone())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["AuthorityClass", "ClaimDisposition", "ClaimKind", "ClaimResolution", "ClaimUnit", "EntityResolution", "GateOutcome", "GateReceipt", "OntologyChangeProposal", "OntologyOperation", "OntologyProperty", "OntologyTargetKind", "ProposalState", "SourceEvidence", "VerifiedOntologyProposal", "stable_digest"];
