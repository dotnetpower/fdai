#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_provider_schema_core_baseline(mut value: std::collections::BTreeMap<String, String>, mut expected_source_revision: String, mut expected_image_digest: String) -> Result<(), &'static str> {
    let max_inactive_revisions: Option<String> = (value.clone()).get("max_inactive_revisions").cloned();
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_provider_schema_evidence(mut value: std::collections::BTreeMap<String, String>, mut expected_application_source: String, mut expected_runtime_revision: String, mut expected_plan_id: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let expected_fields: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("schema_version"), String::from("application_source_commit"), String::from("runtime_image_revision"), String::from("plan_id"), String::from("job_execution_ref_digest"), String::from("job_execution_status"), String::from("checked_at"), String::from("provider_source_revision"), String::from("baseline_digest"), String::from("observed_digest"), String::from("drift_digest"), String::from("disposition"), String::from("durable_generation_digest"), String::from("durable_generation_revision"), String::from("run_receipt_digest"), String::from("review_package_digest"), String::from("heimdall_review_dispatched"), String::from("review_evidence_status"), String::from("correlation_id"), String::from("forseti_risk_verdict"), String::from("forseti_reason"), String::from("saga_audit_entry_hash"), String::from("grants_authority")]);
    let generation_revision: Option<String> = (value.clone()).get("durable_generation_revision").cloned();
    let job_execution_digest: Option<String> = (value.clone()).get("job_execution_ref_digest").cloned();
    let drift_digest: Option<String> = (value.clone()).get("drift_digest").cloned();
    let provider_revision: Option<String> = (value.clone()).get("provider_source_revision").cloned();
    let review_status: Option<String> = (value.clone()).get("review_evidence_status").cloned();
    if (review_status.clone()) == Some(String::from("verified")) {
    } else {
        return Err("github_provider_schema_evidence_invalid");
    }
    Ok(std::collections::BTreeMap::from([(String::from("provider_source_revision"), (provider_revision.clone()).unwrap_or_default()), (String::from("durable_generation_digest"), String::new()), (String::from("durable_generation_revision"), String::new()), (String::from("disposition"), String::new()), (String::from("review_evidence_status"), (review_status.clone()).unwrap_or_default()), (String::from("heimdall_review_dispatched"), String::new()), (String::from("forseti_risk_verdict"), String::new()), (String::from("saga_audit_entry_hash"), String::new())]))
}

