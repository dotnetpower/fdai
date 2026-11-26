use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum InvestigationWorkClass {
    #[default]
    Read,
    ProblemResponse,
    Action,
}

impl InvestigationWorkClass {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Read => "read",
            Self::ProblemResponse => "problem_response",
            Self::Action => "action",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum InvestigationOwner {
    #[default]
    Odin,
    Thor,
    Forseti,
    Huginn,
    Heimdall,
    Vidar,
    Var,
    Bragi,
    Saga,
    Mimir,
    Muninn,
    Norns,
    Njord,
    Freyr,
    Loki,
}

impl InvestigationOwner {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Odin => "Odin",
            Self::Thor => "Thor",
            Self::Forseti => "Forseti",
            Self::Huginn => "Huginn",
            Self::Heimdall => "Heimdall",
            Self::Vidar => "Vidar",
            Self::Var => "Var",
            Self::Bragi => "Bragi",
            Self::Saga => "Saga",
            Self::Mimir => "Mimir",
            Self::Muninn => "Muninn",
            Self::Norns => "Norns",
            Self::Njord => "Njord",
            Self::Freyr => "Freyr",
            Self::Loki => "Loki",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SelectorKind {
    #[default]
    Resource,
    Incident,
    Scope,
    None,
}

impl SelectorKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Resource => "resource",
            Self::Incident => "incident",
            Self::Scope => "scope",
            Self::None => "none",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AnswerContract {
    #[default]
    List,
    State,
    Health,
    Diagnosis,
    Change,
    Topology,
    Knowledge,
    Failure,
}

impl AnswerContract {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::List => "list",
            Self::State => "state",
            Self::Health => "health",
            Self::Diagnosis => "diagnosis",
            Self::Change => "change",
            Self::Topology => "topology",
            Self::Knowledge => "knowledge",
            Self::Failure => "failure",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IntentTerms {
    pub terms: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InvestigationEvidenceRequirements {
    pub authorities: Vec<String>,
    pub required_facets: Vec<String>,
    pub max_age_seconds: i64,
    pub allow_stale: bool,
    pub on_missing: String,
}

impl InvestigationEvidenceRequirements {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(0_i64..=2592000_i64).contains(&self.max_age_seconds) { return Err("max_age_seconds out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InvestigationIntentDefinition {
    pub work_class: InvestigationWorkClass,
    pub owner_agent: InvestigationOwner,
    pub plan_id: String,
    pub selector_kind: SelectorKind,
    pub answer_contract: AnswerContract,
    pub required_any: Vec<String>,
    pub required_all: Vec<IntentTerms>,
    pub excluded_any: Vec<String>,
    pub response_modes: BTreeMap<String, IntentTerms>,
    pub response_mode_order: Vec<String>,
    pub evidence: Box<InvestigationEvidenceRequirements>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InvestigationIntentRegistry {
    pub schema_version: String,
    pub version: String,
    pub suffixes: Vec<String>,
    pub intents: BTreeMap<String, InvestigationIntentDefinition>,
}

pub const SCHEMA_PACKAGE: &str = "fdai.rule_catalog.schema";
pub const SCHEMA_FILE: &str = "investigation_intent.schema.json";
impl InvestigationIntentDefinition {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_definition(&self) -> Result<InvestigationIntentDefinition, &'static str> {
        if ((self.required_any.clone()).is_empty()) && ((self.required_all.clone()).is_empty()) {
            return Err("an investigation intent requires a deterministic matcher");
        }
        Ok(self.clone())
    }
}

impl InvestigationIntentRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn model_post_init(&self, mut context: String) {
        if context.is_empty() {
            return;
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InvestigationIntentRegistryError {
    pub message: String,
}

impl InvestigationIntentRegistryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for InvestigationIntentRegistryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for InvestigationIntentRegistryError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn schema() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_investigation_intents_from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> Result<InvestigationIntentRegistry, &'static str> {
    if raw.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["AnswerContract", "InvestigationEvidenceRequirements", "InvestigationIntentDefinition", "InvestigationIntentRegistry", "InvestigationIntentRegistryError", "InvestigationOwner", "InvestigationWorkClass", "IntentTerms", "SelectorKind", "load_investigation_intents_from_mapping"];
