#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PantheonWeakness {
    #[default]
    PromptContract,
    SemanticRouting,
    OwnerEvidence,
    AnswerRendering,
    AuthoritySafety,
    Handoff,
    MissedT2,
    UnnecessaryT2,
    BudgetMetering,
    Latency,
    ExternalHold,
}

impl PantheonWeakness {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::PromptContract => "prompt_contract",
            Self::SemanticRouting => "semantic_routing",
            Self::OwnerEvidence => "owner_evidence",
            Self::AnswerRendering => "answer_rendering",
            Self::AuthoritySafety => "authority_safety",
            Self::Handoff => "handoff",
            Self::MissedT2 => "missed_t2",
            Self::UnnecessaryT2 => "unnecessary_t2",
            Self::BudgetMetering => "budget_metering",
            Self::Latency => "latency",
            Self::ExternalHold => "external_hold",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum HardeningDisposition {
    #[default]
    Eligible,
    HumanReview,
    Hold,
    NotRequired,
}

impl HardeningDisposition {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Eligible => "eligible",
            Self::HumanReview => "human_review",
            Self::Hold => "hold",
            Self::NotRequired => "not_required",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HardeningDecision {
    pub disposition: HardeningDisposition,
    pub weaknesses: Vec<PantheonWeakness>,
    pub reason: String,
    pub automatic_merge: bool,
}

impl HardeningDecision {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.reason.trim().is_empty() { return Err("reason must be non-empty"); }
        Ok(())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn classify_hardening(mut diagnostic: Option<String>, mut hold_reason: Option<String>) -> HardeningDecision {
    if let Some(mut hold_reason) = hold_reason.clone() {
        return HardeningDecision { reason: hold_reason.trim().to_string(), ..Default::default() };
    }
    let mut weaknesses: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    HardeningDecision { reason: String::from("prompt_or_authority_change_requires_design_review\" if disposition is HardeningDisposition.HUMAN_REVIEW else \"isolated_candidate_allowed"), ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["HardeningDecision", "HardeningDisposition", "PantheonWeakness", "classify_hardening"];
