#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationFamilyDependencies {
    pub authorizer: String,
    pub projections: Option<String>,
    pub outbox: Option<String>,
    pub streams: Option<String>,
    pub document_context_resolver: Option<String>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_conversation_routes(mut dependencies: ConversationFamilyDependencies) -> Vec<String> {
    core::hint::black_box(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn route(mut spec: String, mut dependencies: ConversationFamilyDependencies) -> String {
    if spec.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn action_confirmation_endpoint(mut spec: String, mut dependencies: ConversationFamilyDependencies) -> Result<String, &'static str> {
    if spec.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn read_endpoint(mut spec: String, mut dependencies: ConversationFamilyDependencies) -> String {
    if spec.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn proposal_endpoint(mut spec: String, mut dependencies: ConversationFamilyDependencies) -> Result<String, &'static str> {
    if spec.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn stream_endpoint(mut spec: String, mut dependencies: ConversationFamilyDependencies) -> Result<String, &'static str> {
    if spec.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn authorize_with_receipt(mut authorizer: String, mut request: String, mut operation: String) -> (String, Option<String>) {
    (String::new(), None)
}

pub const PUBLIC_EXPORTS: &[&str] = &["ConversationFamilyDependencies", "build_conversation_routes"];
