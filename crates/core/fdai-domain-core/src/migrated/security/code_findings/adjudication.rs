#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AdjudicationDecision {
    #[default]
    Accepted,
    Rejected,
}

impl AdjudicationDecision {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Accepted => "accepted",
            Self::Rejected => "rejected",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FalsePositiveAdjudication {
    pub pack_id: String,
    pub issue_id: String,
    pub decision: AdjudicationDecision,
    pub claimant: String,
    pub adjudicator: String,
    pub approval_ref: String,
    pub rationale: String,
    pub claim_evidence: String,
    pub decided_at: String,
    pub single_operator_profile: bool,
}

pub const PRINCIPAL: &str = "^[A-Za-z0-9][A-Za-z0-9@._:-]{0,127}$";
pub const APPROVAL: &str = "^[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AdjudicationError {
    pub message: String,
}

impl AdjudicationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AdjudicationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AdjudicationError {}

impl FalsePositiveAdjudication {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn issue_disposition(&self) -> String {
        String::from("false_positive\" if self.decision is AdjudicationDecision.ACCEPTED else \"open")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::too_many_arguments)]
pub fn adjudicate_false_positive(mut claim: String, mut pack_id: String, mut claimant: String, mut adjudicator: String, mut approval_ref: String, mut decision: AdjudicationDecision, mut rationale: String, mut decided_at: String, mut single_operator_profile: bool) -> Result<FalsePositiveAdjudication, &'static str> {
    if ((claimant.clone()) == (adjudicator.clone())) && (!(single_operator_profile)) {
        return Err("the claimant cannot adjudicate their own claim");
    }
    let text: String = (rationale.clone()).trim().to_string();
    if !(((10_i64) <= (((text.clone()).len() as i64))) && ((((text.clone()).len() as i64)) <= (2000_i64))) {
        return Err("rationale must be 10-2000 characters");
    }
    Ok(FalsePositiveAdjudication { pack_id: pack_id.clone(), decision: decision.clone(), claimant: claimant.clone(), adjudicator: adjudicator.clone(), approval_ref: approval_ref.clone(), rationale: text.clone(), decided_at: decided_at.clone(), single_operator_profile: single_operator_profile, ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["AdjudicationDecision", "AdjudicationError", "FalsePositiveAdjudication", "adjudicate_false_positive"];
