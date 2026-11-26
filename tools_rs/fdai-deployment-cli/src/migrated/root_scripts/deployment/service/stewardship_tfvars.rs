#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn stewardship_gitops_binding(mut binding: Option<std::collections::BTreeMap<String, String>>, mut service: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if (!(true)) || ((service.trim().to_string()).is_empty()) {
        return Err("stewardship_gitops_binding service MUST be a non-empty string");
    }
    if (binding.is_some()) && (!(true)) {
        return Err("stewardship_gitops_binding binding MUST be a dict when provided");
    }
    let Some(mut binding) = binding.clone() else { return Ok(std::collections::BTreeMap::<String, String>::new()); };
    if (service.clone()) == (String::from("document-ingestion-api")) {
        return Ok(std::collections::BTreeMap::<String, String>::new());
    }
    Ok(std::collections::BTreeMap::new())
}

