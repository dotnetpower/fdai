#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresStateKeysetMixin {
    pub initialized: bool,
}

impl PostgresStateKeysetMixin {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read_state_keys(&self, mut prefix: String, mut after: String, mut limit: i64) -> Vec<String> {
        read_key_page(String::new(), prefix.clone(), after.clone(), limit, None).await.unwrap_or_else(|_| Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn read_state_keys_before(&self, mut prefix: String, mut before: String, mut after: String, mut limit: i64) -> Result<Vec<String>, &'static str> {
        Ok(read_key_page(String::new(), prefix.clone(), after.clone(), limit, Some(before.clone())).await.unwrap_or_else(|_| Vec::new()))
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn read_key_page(mut store: String, mut prefix: String, mut after: String, mut limit: i64, mut before: Option<String>) -> Result<Vec<String>, &'static str> {
    if ((prefix.clone()).is_empty()) || (((limit) < (1_i64)) || ((!(after.clone()).is_empty()) && (!((after.clone()).starts_with(prefix.as_str()))))) {
        return Err("state key page requires a prefix valid cursor and positive limit");
    }
    let escaped_prefix: String = (((prefix.clone()).replace("\\", "\\\\")).replace("%", "\\%")).replace("_", "\\_");
    Ok(Vec::new())
}

