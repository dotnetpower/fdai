#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn instance_paths(mut graph: String, mut definition: String) -> Result<(Vec<Vec<String>>, Option<i64>), &'static str> {
    Ok((Vec::new(), None))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn instance_path_row(mut path: Vec<String>) -> Result<String, &'static str> {
    if (path.clone()).is_empty() {
        return Err("instance path row requires at least one object");
    }
    let mut values: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("root_id"), String::new()), (String::from("root_type"), String::new()), (String::from("target_id"), String::new()), (String::from("target_type"), String::new()), (String::from("execution_authority"), String::new())]);
    Ok(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["instance_path_row", "instance_paths"];
