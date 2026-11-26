#[derive(Clone, Debug, Default, PartialEq)]
pub struct IndependentHumanAccessObserver {
    pub client: String,
    pub identity: String,
    pub identity_ref: String,
    pub clock: String,
}

impl IndependentHumanAccessObserver {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observe(&self, mut material: String, mut dispatch_receipt_digest: String, mut dispatch_completed_at: String) -> Result<String, &'static str> {
        let headers: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("Authorization"), String::new())]);
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn read(&self, mut path: String, mut headers: std::collections::BTreeMap<String, String>, mut allow_absent: bool) -> Result<Option<std::collections::BTreeMap<String, String>>, &'static str> {
        if path.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["IndependentHumanAccessObserver"];
