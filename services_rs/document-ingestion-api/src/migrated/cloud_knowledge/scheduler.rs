pub trait SourceCheckpointStore {
    fn get(&self, registry_digest: String, source_id: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CloudKnowledgeScheduler {
    pub initialized: bool,
}

impl CloudKnowledgeScheduler {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn tick(&self) -> std::collections::BTreeMap<String, String> {
        let mut counters: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("checked"), String::new()), (String::from("failed"), String::new()), (String::from("status"), String::from("complete"))]);
        counters.clone()
    }
}

