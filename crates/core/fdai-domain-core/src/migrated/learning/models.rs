pub const MAX_ID_CHARS: i64 = 256;
pub const MAX_BODY_CHARS: i64 = 16000;
pub const MAX_CORRECTIONS: i64 = 8;
pub const MAX_EVIDENCE_REFS: i64 = 64;
pub const MAX_OUTCOMES: i64 = 32;
pub const MAX_TOOL_RECEIPTS: i64 = 64;
pub const MAX_MARKDOWN_BYTES: i64 = 65536;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EligibilityReason {
    #[default]
    EligibleComplex,
    EligibleCorrection,
    EligibleRecoveredFailure,
    EligibleRepeatedProcedure,
    Ineligible,
    OptedOut,
    UnsafeContent,
}

impl EligibilityReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::EligibleComplex => "eligible_complex",
            Self::EligibleCorrection => "eligible_correction",
            Self::EligibleRecoveredFailure => "eligible_recovered_failure",
            Self::EligibleRepeatedProcedure => "eligible_repeated_procedure",
            Self::Ineligible => "ineligible",
            Self::OptedOut => "opted_out",
            Self::UnsafeContent => "unsafe_content",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PostTurnProposalKind {
    #[default]
    OperatorMemory,
    RuleHint,
    SkillDraft,
}

impl PostTurnProposalKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::OperatorMemory => "operator_memory",
            Self::RuleHint => "rule_hint",
            Self::SkillDraft => "skill_draft",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ToolReceiptEvidence {
    pub tool_name: String,
    pub status: String,
    pub evidence_ref: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostTurnReviewInput {
    pub review_id: String,
    pub principal_scope: String,
    pub operator_turn_id: String,
    pub assistant_turn_id: String,
    pub completed_at: String,
    pub operator_body: Option<String>,
    pub assistant_body: Option<String>,
    pub tool_receipts: Vec<ToolReceiptEvidence>,
    pub validation_outcomes: Vec<String>,
    pub explicit_corrections: Vec<String>,
    pub evidence_refs: Vec<String>,
    pub memory_scope_kind: Option<String>,
    pub memory_scope_ref: Option<String>,
    pub failure_recovered: bool,
    pub procedure_fingerprint: Option<String>,
    pub repeated_procedure_count: i64,
    pub procedure_receipt: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EligibilityDecision {
    pub eligible: bool,
    pub reasons: Vec<EligibilityReason>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperatorMemoryCandidate {
    pub scope_kind: String,
    pub scope_ref: String,
    pub category: String,
    pub body: String,
    pub evidence_refs: Vec<String>,
    pub confidence: f64,
    pub kind: PostTurnProposalKind,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SkillProposalDraft {
    pub skill_name: String,
    pub markdown: Vec<u8>,
    pub evidence_refs: Vec<String>,
    pub confidence: f64,
    pub kind: PostTurnProposalKind,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleCandidateHint {
    pub proposal_kind: String,
    pub target_ref: String,
    pub pattern: String,
    pub evidence_refs: Vec<String>,
    pub confidence: f64,
    pub kind: PostTurnProposalKind,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct NoImprovement {
    pub reason: String,
}

pub const SAFE_ID: &str = "^[A-Za-z0-9._:-]+$";
impl PostTurnReviewInput {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn body_shared(&self) -> bool {
        (self.operator_body.is_some()) && (self.assistant_body.is_some())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_safe_id(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_bounded_ref(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bounded_optional_body(mut name: String, mut value: Option<String>) {
    if let Some(mut value) = value.clone() {
        let _ = bounded_required_body(name.clone(), value.clone()).unwrap_or_else(|_| ());
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn bounded_required_body(mut name: String, mut value: String) -> Result<(), &'static str> {
    if (((value.clone()).trim().to_string()).is_empty()) || ((((value.clone()).len() as i64)) > (MAX_BODY_CHARS)) {
        return Err("name MUST be non-empty and  _MAX_BODY_CHARS characters");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn bounded_tuple(mut name: String, mut value: Vec<String>, mut maximum: i64) -> Result<(), &'static str> {
    if (((value.clone()).len() as i64)) > (maximum) {
        return Err("PostTurnReviewInput.name exceeds cap lenvalue  maximum");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_proposal_evidence(mut evidence_refs: Vec<String>, mut confidence: f64) -> Result<(), &'static str> {
    if ((evidence_refs.clone()).is_empty()) || ((((evidence_refs.clone()).len() as i64)) > (MAX_EVIDENCE_REFS)) {
        return Err("proposal evidence_refs MUST contain 1 to 64 references");
    }
    for evidence_ref in evidence_refs.clone() {
        let _ = require_safe_id(String::from("proposal.evidence_refs"), evidence_ref.clone()).unwrap_or_else(|_| ());
    }
    if !(((0.0) <= (confidence)) && ((confidence) <= (1.0))) {
        return Err("proposal confidence MUST be in 0 1");
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["EligibilityDecision", "EligibilityReason", "NoImprovement", "OperatorMemoryCandidate", "PostTurnProposal", "PostTurnProposalKind", "PostTurnReviewInput", "RuleCandidateHint", "SkillProposalDraft", "ToolReceiptEvidence"];
