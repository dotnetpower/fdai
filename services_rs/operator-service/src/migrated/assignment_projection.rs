pub trait AssignmentProjectionSource {
    fn read_state(&self, key: String) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn join_assignment_case(mut source: String, mut projected: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let expected: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("proposal_id"), String::new()), (String::from("request_digest"), String::new())]);
    Ok(std::collections::BTreeMap::from([(String::from("state"), String::new()), (String::from("revision"), String::new()), (String::from("reviews"), String::new()), (String::from("effect_receipts"), String::new()), (String::from("core_case_id"), String::new()), (String::from("convergence_status"), String::from("core_observed")), (String::from("degraded_reason"), String::new()), (String::from("superseded_by"), String::new()), (String::from("execution_authority"), String::new())]))
}

pub const PUBLIC_EXPORTS: &[&str] = &["AssignmentProjectionSource", "join_assignment_case"];
