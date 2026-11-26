#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn merge_capability_recall_rows(mut modes: std::collections::BTreeMap<String, String>, mut rows: Vec<std::collections::BTreeMap<String, String>>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    for row in rows.clone() {
        let raw: Option<String> = (row.clone()).get("value").cloned();
        if !(true) {
            return Err("capability_recall is not a JSON object");
        }
        let recall: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("action_type"), String::new()), (String::from("active"), String::new()), (String::from("reason"), String::new()), (String::from("recalled_at"), String::new()), (String::from("lifted_at"), String::new())]);
    }
    Ok(modes.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["merge_capability_recall_rows"];
