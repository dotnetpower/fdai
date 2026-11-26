#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ActionIntentSource {
    #[default]
    OperatorLanguage,
}

impl ActionIntentSource {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::OperatorLanguage => "operator_language",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyActionIntent {
    pub schema_version: String,
    pub source: ActionIntentSource,
    pub actor_ref: String,
    pub purpose: String,
    pub ontology_release_digest: String,
    pub action_type_name: String,
    pub action_type_version: String,
    pub action_declaration_digest: String,
    pub arguments_json: String,
    pub target_selector_json: String,
    pub evidence_refs: Vec<String>,
    pub input_digest: String,
    pub intent_digest: String,
    pub authority: String,
    pub execution_authority: bool,
}

impl OntologyActionIntent {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.authority.as_str(), "candidate_only") { return Err("invalid authority literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub const DIGEST_PATTERN: &str = "^sha256:[a-f0-9]{64}$";
impl OntologyActionIntent {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn arguments(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn target_selector(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn identity_is_exact_and_no_authority(&self) -> Result<OntologyActionIntent, &'static str> {
        let material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), self.schema_version.clone()), (String::from("source"), String::new()), (String::from("actor_ref"), self.actor_ref.clone()), (String::from("purpose"), self.purpose.clone()), (String::from("ontology_release_digest"), self.ontology_release_digest.clone()), (String::from("action_type_name"), self.action_type_name.clone()), (String::from("action_type_version"), self.action_type_version.clone()), (String::from("action_declaration_digest"), self.action_declaration_digest.clone()), (String::from("arguments"), String::new()), (String::from("target_selector"), String::new()), (String::from("evidence_refs"), String::new()), (String::from("input_digest"), self.input_digest.clone()), (String::from("authority"), self.authority.clone()), (String::from("execution_authority"), String::new())]);
        Ok(self.clone())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ActionIntentSource", "OntologyActionIntent"];
