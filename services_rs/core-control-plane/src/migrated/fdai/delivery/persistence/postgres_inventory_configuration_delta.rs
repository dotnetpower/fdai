pub const MAX_RESOURCES: i64 = 50001;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresInventoryConfigurationComparison {
    pub initialized: bool,
}

impl PostgresInventoryConfigurationComparison {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn unchanged_since_previous(&self, mut generation: String) -> (Option<String>, std::collections::BTreeSet<String>) {
        (None, std::collections::BTreeSet::new())
    }
}

