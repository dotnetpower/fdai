#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraSemanticDiff {
    pub additions: Vec<String>,
    pub updates: Vec<String>,
    pub disables: Vec<String>,
    pub reactivations: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraReviewPackage {
    pub prior_revision: String,
    pub proposed_revision: String,
    pub prior_crosswalk_digest: String,
    pub proposed_crosswalk_digest: String,
    pub semantic_diff: Box<WaraSemanticDiff>,
    pub requires_human_review: bool,
    pub changes_active_authority: bool,
    pub content_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraGenerationState {
    pub active: String,
    pub pending_review: Option<String>,
    pub pending_review_digest: Option<String>,
    pub failed_revision: Option<String>,
    pub failure_reason: Option<String>,
}

impl WaraSemanticDiff {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    #[allow(clippy::type_complexity)]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, Vec<String>> {
        std::collections::BTreeMap::from([(String::from("additions"), self.additions.clone()), (String::from("updates"), self.updates.clone()), (String::from("disables"), self.disables.clone()), (String::from("reactivations"), self.reactivations.clone())])
    }
}

impl WaraReviewPackage {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(mut prior: String, mut proposed: String, mut disabled_guids: Vec<String>, mut reactivated_guids: Vec<String>) -> WaraReviewPackage {
        let diff: WaraSemanticDiff = WaraSemanticDiff { reactivations: ((reactivated_guids.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).into_iter().collect::<Vec<String>>(), ..Default::default() };
        let digest_material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("prior_revision"), String::new()), (String::from("proposed_revision"), String::new()), (String::from("prior_crosswalk_digest"), String::new()), (String::from("proposed_crosswalk_digest"), String::new()), (String::from("semantic_diff"), String::new()), (String::from("requires_human_review"), String::new()), (String::from("changes_active_authority"), String::new())]);
        Default::default()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn retain_last_valid_generation(mut current: WaraGenerationState, mut proposed: Option<String>, mut review_package_digest: Option<String>, mut failed_revision: Option<String>, mut failure_reason: Option<String>) -> Result<WaraGenerationState, &'static str> {
    if proposed.is_none() {
        if (!((failure_reason.clone()).is_some())) || (!((failed_revision.clone()).is_some())) {
            return Err("failed WARA generation requires a revision and failure reason");
        }
        return Ok(WaraGenerationState { active: current.active.clone(), pending_review: current.pending_review.clone(), pending_review_digest: current.pending_review_digest.clone(), failed_revision: failed_revision.clone(), failure_reason: failure_reason.clone(), ..Default::default() });
    }
    if (failure_reason.is_some()) || (failed_revision.is_some()) {
        return Err("valid WARA proposal cannot carry failure details");
    }
    let mut review_package_digest: String = match review_package_digest.clone() { Some(_v) if !_v.is_empty() => _v, _ => return Err("valid WARA proposal requires a review package digest") };
    Ok(WaraGenerationState { active: current.active.clone(), pending_review: proposed.clone(), pending_review_digest: Some(review_package_digest.clone()), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn promote_reviewed_generation(mut current: WaraGenerationState, mut approved_package_digest: String) -> Result<WaraGenerationState, &'static str> {
    if ((current.pending_review.clone()).is_none()) || ((current.pending_review_digest.clone()) != Some(approved_package_digest.clone())) {
        return Err("approved WARA review package does not match pending generation");
    }
    Ok(WaraGenerationState { active: (current.pending_review.clone()).unwrap_or_default(), ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["WaraGenerationState", "WaraReviewPackage", "WaraSemanticDiff", "promote_reviewed_generation", "retain_last_valid_generation"];
