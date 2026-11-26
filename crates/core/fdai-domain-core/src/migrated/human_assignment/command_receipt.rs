#[derive(Clone, Debug, Default, PartialEq)]
pub struct AssignmentCommandReceipt {
    pub proposal_id: String,
    pub request_digest: String,
}

impl AssignmentCommandReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("proposal_id"), self.proposal_id.clone()), (String::from("request_digest"), self.request_digest.clone())])
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_dict(mut value: std::collections::BTreeMap<String, String>) -> Result<AssignmentCommandReceipt, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AssignmentCommandReceipt"];
