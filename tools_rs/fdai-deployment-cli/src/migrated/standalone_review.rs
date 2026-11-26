pub const SERVICE_UPDATE_FIELDS: &[&str] = &["service", "image", "source_commit", "update_digest"];
pub const HISTORICAL_RECONCILIATION_FIELDS: &[&str] = &["operation", "variables_digest", "mutations"];
pub const ACTIONS: &[&str] = &["create", "update", "delete", "replace", "read", "no-op"];
pub const ERROR: &str = "standalone plan review is invalid or expired; request a current exact plan";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_plan_review(mut review: std::collections::BTreeMap<String, String>, mut allow_expired: bool) -> Result<(String, i64), &'static str> {
    let stage: Option<String> = (review.clone()).get("stage").cloned();
    let summary: Option<String> = (review.clone()).get("summary").cloned();
    let service_update: Option<String> = (review.clone()).get("service_update").cloned();
    if ((review.clone()).contains_key("operation")) && (!(operation_matches_stage((stage.clone()).unwrap_or_default(), String::new(), (service_update.clone()).unwrap_or_default()))) {
        return Err("_ERROR");
    }
    let historical_reconciliation: Option<String> = (review.clone()).get("historical_reconciliation").cloned();
    let residual_recovery: Option<String> = (review.clone()).get("residual_recovery").cloned();
    let residual_successor: Option<String> = (review.clone()).get("residual_successor").cloned();
    if ((review.clone()).contains_key("runtime_profile_digest")) || ((review.clone()).contains_key("runtime_platform")) {
        let runtime_profile_digest: Option<String> = (review.clone()).get("runtime_profile_digest").cloned();
    }
    let expiry: Option<String> = (review.clone()).get("expires_at").cloned();
    if !(true) {
        return Err("_ERROR");
    }
    Ok((String::new(), 0_i64))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn operation_matches_stage(mut stage: String, mut operation: String, mut service_update: String) -> bool {
    if !(true) {
        return false;
    }
    if (stage.clone()) == (String::from("runtime")) {
        return matches!(operation.as_str(), "runtime" | "runtime-cluster");
    }
    if (stage.clone()) == (String::from("application")) {
        return matches!(operation.as_str(), "application" | "application-input-rebind-update" | "license-application-update");
    }
    (operation.clone()) == (stage.clone())
}

