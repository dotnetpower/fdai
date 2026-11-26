pub const MAX_TEXT_CHARS: i64 = 16384;
pub const MAX_RATIONALE_CHARS: i64 = 1000;
pub const MAX_EVIDENCE_REFS: i64 = 64;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AssuranceCriterion {
    #[default]
    FactualCorrectness,
    IntentResolution,
    Completeness,
    Calibration,
    Actionability,
    Clarity,
}

impl AssuranceCriterion {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::FactualCorrectness => "factual_correctness",
            Self::IntentResolution => "intent_resolution",
            Self::Completeness => "completeness",
            Self::Calibration => "calibration",
            Self::Actionability => "actionability",
            Self::Clarity => "clarity",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AssuranceVerdict {
    #[default]
    Pass,
    Fail,
    Inconclusive,
}

impl AssuranceVerdict {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pass => "pass",
            Self::Fail => "fail",
            Self::Inconclusive => "inconclusive",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AssessmentState {
    #[default]
    Completed,
    Deferred,
    Disputed,
}

impl AssessmentState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Completed => "completed",
            Self::Deferred => "deferred",
            Self::Disputed => "disputed",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DisputeReason {
    #[default]
    WrongFact,
    MissingIntent,
    StaleEvidence,
    WrongScope,
    InappropriateAbstention,
    LanguageQuality,
}

impl DisputeReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::WrongFact => "wrong_fact",
            Self::MissingIntent => "missing_intent",
            Self::StaleEvidence => "stale_evidence",
            Self::WrongScope => "wrong_scope",
            Self::InappropriateAbstention => "inappropriate_abstention",
            Self::LanguageQuality => "language_quality",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TurnAssessmentInput {
    pub turn_id: String,
    pub conversation_id: String,
    pub principal_scope: String,
    pub question: String,
    pub answer: String,
    pub question_digest: String,
    pub answer_digest: String,
    pub evidence_manifest_digest: String,
    pub evidence_refs: Vec<String>,
    pub verification_status: String,
    pub verification_authority: String,
    pub checks_completed: i64,
    pub checks_total: i64,
    pub failed_claim_ids: Vec<String>,
    pub verification_reason_code: String,
    pub verification_route_id: Option<String>,
    pub evidence_complete: Option<bool>,
    pub ontology_release: Option<String>,
    pub graph_revision: Option<String>,
    pub locale: String,
    pub answer_model_identity: Option<String>,
    pub answer_model_family: Option<String>,
    pub deterministic_answer: bool,
    pub reference_facts: Vec<String>,
}

impl TurnAssessmentInput {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.turn_id.trim().is_empty() { return Err("turn_id must be non-empty"); }
        if self.conversation_id.trim().is_empty() { return Err("conversation_id must be non-empty"); }
        if self.principal_scope.trim().is_empty() { return Err("principal_scope must be non-empty"); }
        if self.question.trim().is_empty() { return Err("question must be non-empty"); }
        if self.answer.trim().is_empty() { return Err("answer must be non-empty"); }
        if self.question_digest.trim().is_empty() { return Err("question_digest must be non-empty"); }
        if self.answer_digest.trim().is_empty() { return Err("answer_digest must be non-empty"); }
        if self.evidence_manifest_digest.trim().is_empty() { return Err("evidence_manifest_digest must be non-empty"); }
        if self.verification_status.trim().is_empty() { return Err("verification_status must be non-empty"); }
        if self.verification_authority.trim().is_empty() { return Err("verification_authority must be non-empty"); }
        if self.verification_reason_code.trim().is_empty() { return Err("verification_reason_code must be non-empty"); }
        if self.locale.trim().is_empty() { return Err("locale must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CriterionScore {
    pub criterion: AssuranceCriterion,
    pub score: i64,
    pub rationale: String,
    pub evidence_refs: Vec<String>,
}

impl CriterionScore {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.rationale.trim().is_empty() { return Err("rationale must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EvaluatorOutput {
    pub model_identity: String,
    pub model_family: String,
    pub scores: Vec<CriterionScore>,
    pub confidence: f64,
    pub prompt_tokens: i64,
    pub completion_tokens: i64,
    pub cost_microusd: i64,
    pub prompt_profile_evidence: Option<String>,
}

impl EvaluatorOutput {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.model_identity.trim().is_empty() { return Err("model_identity must be non-empty"); }
        if self.model_family.trim().is_empty() { return Err("model_family must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AssuranceDecision {
    pub verdict: AssuranceVerdict,
    pub content_score: f64,
    pub confidence: f64,
    pub criteria: Vec<CriterionScore>,
    pub reasons: Vec<String>,
    pub evaluator_identities: Vec<String>,
    pub disagreement: bool,
    pub model_calls: i64,
    pub prompt_tokens: i64,
    pub completion_tokens: i64,
    pub cost_microusd: i64,
    pub prompt_profile_evidence: Vec<String>,
    pub pantheon_diagnostic: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DeterministicAssessment {
    pub verdict: Option<AssuranceVerdict>,
    pub reasons: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DebateContext {
    pub first: Box<EvaluatorOutput>,
    pub second: Box<EvaluatorOutput>,
    pub disputed_criteria: Vec<AssuranceCriterion>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AssessmentRecord {
    pub assessment_id: String,
    pub turn_id: String,
    pub conversation_id: String,
    pub principal_scope: String,
    pub question_digest: String,
    pub answer_digest: String,
    pub evidence_manifest_digest: String,
    pub rubric_version: String,
    pub model_set_digest: String,
    pub decision: Box<AssuranceDecision>,
    pub assessed_at: String,
    pub state: AssessmentState,
    pub dispute_ids: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DisputeRecord {
    pub dispute_id: String,
    pub assessment_id: String,
    pub principal_scope: String,
    pub reported_by: String,
    pub reason: DisputeReason,
    pub detail: String,
    pub evidence_refs: Vec<String>,
    pub reported_at: String,
}

impl DisputeRecord {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.dispute_id.trim().is_empty() { return Err("dispute_id must be non-empty"); }
        if self.assessment_id.trim().is_empty() { return Err("assessment_id must be non-empty"); }
        if self.principal_scope.trim().is_empty() { return Err("principal_scope must be non-empty"); }
        if self.reported_by.trim().is_empty() { return Err("reported_by must be non-empty"); }
        if self.detail.trim().is_empty() { return Err("detail must be non-empty"); }
        if self.reported_at.trim().is_empty() { return Err("reported_at must be non-empty"); }
        Ok(())
    }
}

impl EvaluatorOutput {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn usage(&self) -> (i64, i64, i64) {
        (self.prompt_tokens, self.completion_tokens, self.cost_microusd)
    }
}

impl DeterministicAssessment {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn needs_semantic_review(&self) -> bool {
        self.verdict.is_none()
    }
}

pub trait ConversationAssuranceEvaluator {
    fn model_identity(&self) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["CRITERION_WEIGHTS", "AssessmentRecord", "AssessmentState", "AssuranceCriterion", "AssuranceDecision", "AssuranceVerdict", "ConversationAssuranceEvaluator", "CriterionScore", "DebateContext", "DeterministicAssessment", "DisputeReason", "DisputeRecord", "EvaluatorOutput", "TurnAssessmentInput"];
