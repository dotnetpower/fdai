#[derive(Clone, Debug, Default, PartialEq)]
pub struct AssignmentIamRequestReader {
    pub cases: String,
}

impl AssignmentIamRequestReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn read(&self, mut notice: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(std::collections::BTreeMap::from([(String::from("action_type"), String::from("ops.revoke-human-access\" if revoke else \"ops.apply-human-access")), (String::from("resource_id"), String::new()), (String::from("params"), String::new()), (String::from("initiator_principal"), String::new()), (String::from("quorum_required"), String::new()), (String::from("risk_verdict"), String::from("hil")), (String::from("reason"), String::from("assignment_iam_requires_current_human_review")), (String::from("resolved_autonomy_ceiling"), String::from("shadow_only"))]))
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AssignmentIamRequestReader"];
