#[derive(Clone, Debug, Default, PartialEq)]
pub struct MimirCatalogPromotionOutcome {
    pub problem_fingerprint: String,
    pub promotion_pr: String,
    pub correlation_id: String,
    pub outcome: String,
    pub rule_id: String,
    pub promoted_at: String,
    pub candidate_digest: Option<String>,
    pub package_digest: Option<String>,
    pub review_ref: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MimirRegressionResult {
    pub passed: bool,
    pub started_at: String,
    pub completed_at: String,
    pub evidence_ref: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MimirRuleSourcePollResult {
    pub checked: i64,
    pub changed: i64,
    pub evidence_ref: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MimirDeprecationCandidate {
    pub rule_id: String,
    pub reason: String,
    pub evidence_ref: String,
    pub observed_at: String,
}

pub trait MimirCatalogPromotionOutcomeReader {
    fn read_promotion_outcomes(&self, limit: i64, now: String) -> String;
}

pub trait MimirRegressionRunner {
    fn run_regression(&self, outcome: MimirCatalogPromotionOutcome, now: String) -> String;
}

pub trait MimirRuleSourcePoller {
    fn poll_rule_sources(&self, limit: i64, now: String) -> String;
}

pub trait MimirRuleDeprecationReader {
    fn stale_or_retired_rules(&self, limit: i64, now: String) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn promotion_outcome_is_authoritative(mut outcome: MimirCatalogPromotionOutcome) -> bool {
    core::hint::black_box(false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn regression_result_is_clean(mut result: MimirRegressionResult) -> bool {
    core::hint::black_box(false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn norns_issue_close_support(mut payload: std::collections::BTreeMap<String, String>) -> Option<std::collections::BTreeMap<String, String>> {
    if (((payload.clone()).get("producer_principal").cloned()) != Some(String::from("Norns"))) || (((payload.clone()).get("kind").cloned()) != Some(String::from("issue_close_eligibility_signal"))) {
        return None;
    }
    let raw: Option<String> = (payload.clone()).get("closure_eligibility").cloned();
    if !(true) {
        return None;
    }
    Some(std::collections::BTreeMap::from([(String::from("fingerprint"), String::new()), (String::from("occurrence_count"), String::new()), (String::from("idempotency_key"), String::new()), (String::from("correlation_id"), String::new()), (String::from("inert"), String::new()), (String::from("grants_issue_authority"), String::new())]))
}

