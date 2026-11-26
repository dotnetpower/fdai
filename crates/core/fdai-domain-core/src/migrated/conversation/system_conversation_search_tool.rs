#[derive(Clone, Debug, Default, PartialEq)]
pub struct SearchConversationsTool {
    pub side_effect_class: String,
}

impl SearchConversationsTool {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn call(&self, mut arguments: std::collections::BTreeMap<String, String>, mut principal: String) -> String {
        if arguments.is_empty() {
            return String::new();
        }
        String::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["SearchConversationsTool"];
