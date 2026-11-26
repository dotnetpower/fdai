#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresRuleActivationReceiptReader {
    pub config: String,
}

impl PostgresRuleActivationReceiptReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn read_state(&self, mut key: String) -> Result<Option<std::collections::BTreeMap<String, String>>, &'static str> {
        if key.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresRuleActivationReceiptReader"];
