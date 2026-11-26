pub const RATIONALE_AUDIT_CAP: i64 = 500;

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn quality_decision_audit_fields(mut decision: String, mut include_rationale: bool) -> std::collections::BTreeMap<String, String> {
    let mut fields: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("outcome"), String::new()), (String::from("candidate_action_type"), String::new()), (String::from("candidate_target_resource_ref"), String::new()), (String::from("aggregate_confidence"), String::new()), (String::from("deterministic_evidence"), String::new()), (String::from("reasons"), String::new()), (String::from("grounded_rule_ids"), String::new()), (String::from("model_votes"), String::new()), (String::from("rubric_verdict"), String::new()), (String::from("rubric_min_score"), String::new()), (String::from("rubric_shadow"), String::new()), (String::from("rubric_scores"), String::new())]);
    fields.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn prompt_replay_manifest_fields(mut manifest: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("system_text_sha256"), String::new()), (String::from("token_estimate"), String::new()), (String::from("profile_id"), String::new()), (String::from("profile_version"), String::new()), (String::from("profile_digest"), String::new()), (String::from("system_token_budget"), String::new()), (String::from("request_token_budget"), String::new()), (String::from("reserved_output_tokens"), String::new()), (String::from("canary_tokens"), String::new()), (String::from("ablation_profile"), String::new()), (String::from("ablated_layers"), String::new()), (String::from("layer_manifest"), String::new()), (String::from("skill_records"), String::new()), (String::from("skill_bundle_records"), String::new())])
}

