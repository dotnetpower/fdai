#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn add_prepare_command(mut sub: String) {
    if sub.is_empty() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn prepare_scan(mut args: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut header: Option<String> = None;
    Ok(std::collections::BTreeMap::from([(String::from("ok"), String::new()), (String::from("repository_alias"), String::new()), (String::from("revision"), String::new()), (String::from("revision_kind"), String::new()), (String::from("manifest_digest"), String::new()), (String::from("tree_digest"), String::new())]))
}

