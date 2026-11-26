#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperatorFamilyAuthorizer {
    pub authenticator: String,
}

pub const READER_CHAT_OPERATIONS: &[&str] = &["chat.stream"];
impl OperatorFamilyAuthorizer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn authorize(&self, mut request: String, mut operation: String) -> String {
        if request.is_empty() {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn authorize_with_receipt(&self, mut request: String, mut operation: String) -> Result<(String, Option<String>), &'static str> {
        Ok((String::new(), None))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn iam(&self, mut request: String) -> String {
        if request.is_empty() {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn workflow(&self, mut request: String, mut required_roles: std::collections::BTreeSet<String>) -> String {
        if request.is_empty() {
            return String::new();
        }
        String::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["OperatorFamilyAuthorizer"];
