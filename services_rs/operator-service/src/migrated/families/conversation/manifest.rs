#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationRouteSpec {
    pub method: String,
    pub path: String,
    pub name: String,
    pub operation: String,
    pub mode: String,
    pub success_status: i64,
    pub max_body_bytes: i64,
    pub requires_confirmation: bool,
}

impl ConversationRouteSpec {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.method.as_str(), "DELETE" | "GET" | "POST" | "PUT") { return Err("invalid method literal"); }
        if !matches!(self.mode.as_str(), "action_confirmation" | "read" | "proposal" | "stream") { return Err("invalid mode literal"); }
        Ok(())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_busy_input_materializer() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_behavior_knowledge_resolver(mut index: String) -> String {
    if index.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["CONVERSATION_ROUTE_MANIFEST", "ConversationRouteSpec", "build_behavior_knowledge_resolver", "build_busy_input_materializer"];
