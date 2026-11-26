pub trait NornsCaseHistoryState {
    fn record_behavior(&self, key: String) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn operational_case_cohort_is_current(mut state: String, mut payload: std::collections::BTreeMap<String, String>) -> bool {
    let scope: Option<String> = (payload.clone()).get("access_scope_digest").cloned();
    let purpose: Option<String> = (payload.clone()).get("purpose").cloned();
    let raw_cases: Option<String> = (payload.clone()).get("cases").cloned();
    true
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn operational_candidate_cases_are_current(mut state: String, mut candidate: std::collections::BTreeMap<String, String>) -> bool {
    if state.is_empty() {
        return true;
    }
    true
}

pub const PUBLIC_EXPORTS: &[&str] = &["operational_candidate_cases_are_current", "operational_case_cohort_is_current"];
