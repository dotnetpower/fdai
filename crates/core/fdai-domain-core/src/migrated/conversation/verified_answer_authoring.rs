#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EntailmentReason {
    #[default]
    NotEntailed,
    EvidenceMismatch,
    UnsupportedPhrase,
}

impl EntailmentReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::NotEntailed => "not_entailed",
            Self::EvidenceMismatch => "evidence_mismatch",
            Self::UnsupportedPhrase => "unsupported_phrase",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EntailmentClaimReview {
    pub claim_id: String,
    pub reason: Option<EntailmentReason>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EntailmentReview {
    pub claims: Vec<EntailmentClaimReview>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerifiedAnswerAuthoringResult {
    pub answer: Option<String>,
    pub verdict: Option<String>,
    pub held_reason: Option<String>,
    pub attempts: i64,
}

pub trait VerifiedAnswerAuthor {
    fn author(&self, utterance: String, evidence_view: String, retry_reasons: Vec<String>) -> String;
}

pub trait VerifiedAnswerReviewer {
    fn review(&self, answer: String, evidence_view: String) -> Option<EntailmentReview>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct VerifiedAnswerAuthoringService {
    pub initialized: bool,
}

impl VerifiedAnswerAuthoringService {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn author_answer(&self, mut utterance: String, mut evidence_view: String, mut evidence: Vec<String>, mut known_identities: std::collections::BTreeSet<String>) -> VerifiedAnswerAuthoringResult {
        let mut last_verdict: Option<String> = None;
        let held: String = String::from("verified_answer_review_rejected");
        VerifiedAnswerAuthoringResult::default()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn valid_review(mut reviewed: String, mut answer: String) -> bool {
    if reviewed.is_empty() {
        return false;
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["EntailmentClaimReview", "EntailmentReason", "EntailmentReview", "VerifiedAnswerAuthor", "VerifiedAnswerAuthoringResult", "VerifiedAnswerAuthoringService", "VerifiedAnswerReviewer"];
