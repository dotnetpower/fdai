#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PromotionReviewDecision {
    #[default]
    EligibleForReview,
    Hold,
}

impl PromotionReviewDecision {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::EligibleForReview => "eligible_for_review",
            Self::Hold => "hold",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SurfacePromotionReviewAssessment {
    pub decision: PromotionReviewDecision,
    pub reason_codes: Vec<String>,
    pub review_authority: String,
    pub promotion_authority: bool,
    pub execution_authority: bool,
}

pub const DIGEST: &str = "^sha256:[a-f0-9]{64}$";
pub const IDENTIFIER: &str = "^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,511}$";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn assess_surface_promotion_review(mut receipt: String, mut current_policy: String, mut expected_surface_digest: String, mut expected_generation_digest: String, mut expected_catalog_digest: String, mut expected_dataset_digest: String, mut expected_evaluator_ref: String) -> Result<SurfacePromotionReviewAssessment, &'static str> {
    let mut reasons: Vec<String> = Vec::<String>::new();
    let ordered_reasons: Vec<String> = { let mut _v = reasons.clone(); _v.sort(); _v };
    Ok(SurfacePromotionReviewAssessment { reason_codes: ordered_reasons.clone(), ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["PromotionReviewDecision", "SurfacePromotionReviewAssessment", "assess_surface_promotion_review"];
