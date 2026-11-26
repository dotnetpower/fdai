#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConfigurationRevisionCandidate {
    pub package: String,
    pub installation_id: String,
    pub entity_bindings: Vec<String>,
    pub configuration_key: String,
    pub installation_key_digest: String,
    pub sealed_keys: Vec<String>,
    pub expected_predecessor: Option<String>,
    pub history: Vec<String>,
    #[allow(clippy::type_complexity)]
    pub history_bindings: Option<Vec<String>>,
}

impl ConfigurationRevisionCandidate {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn resolve(&self, mut release_id: String, mut release: String, mut entity_ids: std::collections::BTreeSet<String>, mut installation_id: String) -> Result<String, &'static str> {
        if release_id.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

