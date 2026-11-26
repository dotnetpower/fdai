#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn read_findings(mut fetch_all: String, mut query: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::from([(String::from("source"), String::from("runtime-observed")), (String::from("observed_at"), String::new()), (String::from("total_count"), String::new()), (String::from("items"), String::new()), (String::from("next_cursor"), String::new()), (String::from("execution_authority"), String::new())]))
}

