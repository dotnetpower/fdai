#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn add_input_verification_command(mut sub: String) {
    if sub.is_empty() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn verify_scanner_input(mut args: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::from([(String::from("ok"), String::new()), (String::from("tree_digest"), String::new())]))
}

