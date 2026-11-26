#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub async fn compare_and_set_state_with_approval_guard(mut connection: String, mut set_statement_timeout: String, mut append_audit_in_transaction: String, mut key: String, mut value: std::collections::BTreeMap<String, String>, mut expected_revision: i64, mut approval_key: String, mut expected_approval_revision: i64, mut expected_approval_process_id: String, mut expected_approval_step_id: String, mut expected_approval_attempt: i64, mut expected_approval_requester: String, mut expected_approval_quorum: i64, mut expected_no_self_approval: bool, mut expected_approval_decisions: Vec<(String, String, String)>, mut evaluated_at: String, mut admission_verified_at: String, mut admission_valid_until: String, mut audit_entry: std::collections::BTreeMap<String, String>) -> Result<bool, &'static str> {
    if ((expected_revision) < (0_i64)) || ((expected_approval_revision) < (0_i64)) {
        return Err("guarded expected revisions MUST be  0");
    }
    Ok(true)
}

pub const PUBLIC_EXPORTS: &[&str] = &["compare_and_set_state_with_approval_guard"];
