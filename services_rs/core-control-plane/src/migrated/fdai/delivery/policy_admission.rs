#[derive(Clone, Debug, Default, PartialEq)]
pub struct OpaAdmissionPolicyEvaluator {
    pub opa_binary: String,
    pub capabilities_file: Option<String>,
    pub timeout_seconds: f64,
    pub signature_verifier: Option<String>,
}

impl OpaAdmissionPolicyEvaluator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn evaluate(&self, mut revision: String, mut action_input: std::collections::BTreeMap<String, String>) -> String {
        if revision.is_empty() {
            return String::new();
        }
        String::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["OpaAdmissionPolicyEvaluator"];
