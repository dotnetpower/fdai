pub const MAX_BYTES: i64 = 4000000;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzCliManagementReader {
    pub initialized: bool,
}

impl AzCliManagementReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn get(&self, mut path: String, mut api_version: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(std::collections::BTreeMap::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn run(&self, mut path: String, mut api_version: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(std::collections::BTreeMap::new())
    }
}

