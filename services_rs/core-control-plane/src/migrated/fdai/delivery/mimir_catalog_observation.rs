pub const MAX_RETAINED_OBSERVATIONS: i64 = 1000;

pub const KEY: &str = "pantheon/mimir/active-rule-generation-observation";
pub const ARTIFACT_PREFIX: &str = "pantheon/mimir/rule-source-observation/";
pub trait ActiveRuleGenerationReader {
    fn rule_generation_snapshot(&self) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MimirActiveCatalogPoller {
    pub initialized: bool,
}

impl MimirActiveCatalogPoller {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn poll_rule_sources(&self, mut limit: i64, mut now: String) -> Result<String, &'static str> {
        let record: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("generation_digest"), String::new()), (String::from("membership_digest"), String::new()), (String::from("rule_count"), String::new()), (String::from("recorded_at"), String::new()), (String::from("execution_authority"), String::new())]);
        let audit: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("action_kind"), String::from("mimir.rule-source.observed")), (String::from("principal"), String::from("Mimir")), (String::from("generation_digest"), String::new()), (String::from("evidence_ref"), String::new()), (String::from("execution_authority"), String::new())]);
        Err("Rule observation CAS bound exceeded")
    }
}

