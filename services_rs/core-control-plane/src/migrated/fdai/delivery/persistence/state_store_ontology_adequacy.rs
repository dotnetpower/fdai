#[derive(Clone, Debug, Default, PartialEq)]
pub struct StateStoreOntologyAdequacyReviewSink {
    pub store: String,
}

pub const PREFIX: &str = "ontology-adequacy-review";
impl StateStoreOntologyAdequacyReviewSink {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn submit(&self, mut review: String) -> Result<(), &'static str> {
        let payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("review_id"), String::new()), (String::from("attribution_id"), String::new()), (String::from("state"), String::new()), (String::from("candidate_kind"), String::new()), (String::from("competency_question_digest"), String::new()), (String::from("ontology_release"), String::new()), (String::from("graph_revision"), String::new()), (String::from("evidence_refs"), String::new()), (String::from("reason_codes"), String::new()), (String::from("revision"), String::new())]);
        Ok(())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["StateStoreOntologyAdequacyReviewSink"];
