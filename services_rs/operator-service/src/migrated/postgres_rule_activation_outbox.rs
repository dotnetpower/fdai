#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresRuleActivationOutbox {
    pub config: String,
}

impl PostgresRuleActivationOutbox {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn query(&self, mut sql: String, mut parameters: std::collections::BTreeMap<String, String>) -> Vec<std::collections::BTreeMap<String, String>> {
        if sql.is_empty() {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn claim(&self) -> Result<Option<String>, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn finish(&self, mut claim: String, mut rejected: bool) -> bool {
        if claim.is_empty() {
            return false;
        }
        false
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn release(&self, mut claim: String) {
        if claim.is_empty() {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn transition(&self, mut claim: String, mut state: String) -> Vec<std::collections::BTreeMap<String, String>> {
        self.query(String::new(), std::collections::BTreeMap::new()).await
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_rule_activation_notice_bridge(mut environment: String, mut publisher: Option<String>) -> Option<String> {
    let store: PostgresRuleActivationOutbox = PostgresRuleActivationOutbox::default();
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresRuleActivationOutbox", "build_rule_activation_notice_bridge"];
