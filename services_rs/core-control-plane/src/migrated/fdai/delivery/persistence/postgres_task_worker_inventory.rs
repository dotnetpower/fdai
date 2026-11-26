#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresTaskWorkerInventoryReader {
    pub initialized: bool,
}

impl PostgresTaskWorkerInventoryReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn call(&self, mut resource_ref: String) -> Option<std::collections::BTreeMap<String, String>> {
        Some(std::collections::BTreeMap::from([(String::from("resource_id"), String::new()), (String::from("resource_type"), String::new()), (String::from("name"), String::new()), (String::from("state"), String::new()), (String::from("snapshot_id"), String::new()), (String::from("observed_at"), String::new())]))
    }
}

