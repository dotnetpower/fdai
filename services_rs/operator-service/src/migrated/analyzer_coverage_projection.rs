pub const MAX_RESOURCE_TYPES: i64 = 32;
pub const MAX_RESOURCES: i64 = 1000;

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn project_analyzer_coverage(mut value: String, mut run_attempt_id: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let root: std::collections::BTreeMap<String, String> = mapping(value.clone(), String::from("analyzer coverage")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let schema_version: Option<String> = (root.clone()).get("schema_version").cloned();
    if !(matches!(((schema_version.clone()).unwrap_or_default()).as_str(), "1.0.0" | "1.1.0")) {
        return Err("analyzer coverage schema is unsupported");
    }
    let legacy: bool = (schema_version.clone()) == Some(String::from("1.0.0"));
    let status: String = text(String::new(), String::from("analyzer coverage status"), 0_i64).unwrap_or_else(|_| String::new());
    let reason: Option<String> = (root.clone()).get("unavailable_reason").cloned();
    if (status.clone()) == (String::from("unavailable")) {
        return Ok(unavailable_analyzer_coverage(text((reason.clone()).unwrap_or_default(), String::from("analyzer coverage unavailable reason"), 0_i64).unwrap_or_else(|_| String::new()), Some(run_attempt_id.clone())));
    }
    if ((status.clone()) != (String::from("available"))) || (reason.is_some()) {
        return Err("analyzer coverage availability is malformed");
    }
    let resource_type_values: Vec<String> = sequence(String::new(), String::from("analyzer coverage resource types"), MAX_RESOURCE_TYPES).unwrap_or_else(|_| Vec::new());
    let resource_values: Vec<String> = sequence(String::new(), String::from("analyzer coverage resources"), MAX_RESOURCES).unwrap_or_else(|_| Vec::new());
    let projected: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.1.0")), (String::from("status"), String::from("available")), (String::from("unavailable_reason"), String::new()), (String::from("run_attempt_id"), text(run_attempt_id.clone(), String::from("analyzer coverage run attempt"), 0_i64).unwrap_or_else(|_| String::new())), (String::from("candidate_count"), String::new()), (String::from("selected_count"), String::new()), (String::from("evaluated_count"), String::new()), (String::from("held_count"), String::new()), (String::from("finding_count"), String::new()), (String::from("unsupported_count"), String::new()), (String::from("error_count"), String::new()), (String::from("unattributed_error_count"), String::new()), (String::from("unattributed_error_codes"), String::new()), (String::from("publication_counts"), String::new()), (String::from("resource_types"), String::new()), (String::from("resources"), String::new()), (String::from("cause_claim_supported"), String::new()), (String::from("execution_authority"), String::new())]);
    let _ = reconcile(projected.clone()).unwrap_or_else(|_| ());
    Ok(projected.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn unavailable_analyzer_coverage(mut reason: String, mut run_attempt_id: Option<String>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.1.0")), (String::from("status"), String::from("unavailable")), (String::from("unavailable_reason"), text(reason.clone(), String::from("analyzer coverage unavailable reason"), 0_i64).unwrap_or_else(|_| String::new())), (String::from("run_attempt_id"), String::new()), (String::from("cause_claim_supported"), String::new()), (String::from("execution_authority"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn resource_type(mut value: String, mut legacy: bool) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let row: std::collections::BTreeMap<String, String> = mapping(value.clone(), String::from("analyzer coverage resource type")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let candidate_count: i64 = count(row.clone(), String::from("candidate_count"), String::from("analyzer coverage resource type")).unwrap_or_else(|_| 0_i64);
    let selected_count: i64 = count(row.clone(), String::from("selected_count"), String::from("analyzer coverage resource type")).unwrap_or_else(|_| 0_i64);
    let held_count: i64 = count(row.clone(), String::from("held_count"), String::from("analyzer coverage resource type")).unwrap_or_else(|_| 0_i64);
    if (candidate_count) != ((selected_count).saturating_add(held_count)) {
        return Err("analyzer coverage resource type candidate totals do not reconcile");
    }
    Ok(std::collections::BTreeMap::from([(String::from("resource_type"), text(String::new(), String::from("analyzer coverage resource type"), 0_i64).unwrap_or_else(|_| String::new())), (String::from("candidate_count"), String::new()), (String::from("selected_count"), String::new()), (String::from("evaluated_count"), String::new()), (String::from("held_count"), String::new()), (String::from("held_reason_counts"), String::new()), (String::from("finding_count"), String::new()), (String::from("unsupported_count"), String::new()), (String::from("error_count"), String::new()), (String::from("error_codes"), String::new()), (String::from("publication_counts"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn resource(mut value: String, mut legacy: bool) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let row: std::collections::BTreeMap<String, String> = mapping(value.clone(), String::from("analyzer coverage resource")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let state: String = text(String::new(), String::from("analyzer coverage evaluation state"), 0_i64).unwrap_or_else(|_| String::new());
    let finding_count: i64 = count(row.clone(), String::from("finding_count"), String::from("analyzer coverage resource")).unwrap_or_else(|_| 0_i64);
    let unsupported_count: i64 = count(row.clone(), String::from("unsupported_count"), String::from("analyzer coverage resource")).unwrap_or_else(|_| 0_i64);
    let error_count: i64 = count(row.clone(), String::from("error_count"), String::from("analyzer coverage resource")).unwrap_or_else(|_| 0_i64);
    let error_codes: Vec<String> = legacy_error_codes(row.clone(), legacy, String::from("resource"));
    if ((error_count) == (0_i64)) != ((((error_codes.clone()).len() as i64)) == (0_i64)) {
        return Err("analyzer coverage resource error codes are inconsistent");
    }
    let publications: std::collections::BTreeMap<String, i64> = publication_counts(String::new(), String::from("analyzer coverage resource publication counts")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    if ((state.clone()) == (String::from("evaluated_no_finding"))) && (((finding_count) != (0_i64)) || (((error_count) != (0_i64)) || ((unsupported_count) != (0_i64)))) {
        return Err("analyzer coverage no-finding evaluation is inconsistent");
    }
    if ((state.clone()) == (String::from("finding"))) && ((finding_count) == (0_i64)) {
        return Err("analyzer coverage finding state has no finding");
    }
    if ((state.clone()) == (String::from("evaluation_error"))) && ((error_count) == (0_i64)) {
        return Err("analyzer coverage error state has no error");
    }
    if ((state.clone()) == (String::from("unsupported"))) && ((unsupported_count) == (0_i64)) {
        return Err("analyzer coverage unsupported state is inconsistent");
    }
    Ok(std::collections::BTreeMap::from([(String::from("resource_ref"), text(String::new(), String::from("analyzer coverage resource reference"), 512_i64).unwrap_or_else(|_| String::new())), (String::from("resource_type"), text(String::new(), String::from("analyzer coverage resource type"), 0_i64).unwrap_or_else(|_| String::new())), (String::from("resource_kind"), text(String::new(), String::from("analyzer coverage resource kind"), 0_i64).unwrap_or_else(|_| String::new())), (String::from("evaluation_state"), state.clone()), (String::from("finding_count"), String::new()), (String::from("unsupported_count"), String::new()), (String::from("error_count"), String::new()), (String::from("error_codes"), String::new()), (String::from("publication_counts"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn reconcile(mut coverage: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
    let totals: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("candidate_count"), String::new()), (String::from("selected_count"), String::new()), (String::from("evaluated_count"), String::new()), (String::from("held_count"), String::new()), (String::from("finding_count"), String::new()), (String::from("unsupported_count"), String::new())]);
    let candidate_count: i64 = count(coverage.clone(), String::from("candidate_count"), String::from("analyzer coverage")).unwrap_or_else(|_| 0_i64);
    let selected_count: i64 = count(coverage.clone(), String::from("selected_count"), String::from("analyzer coverage")).unwrap_or_else(|_| 0_i64);
    let held_count: i64 = count(coverage.clone(), String::from("held_count"), String::from("analyzer coverage")).unwrap_or_else(|_| 0_i64);
    if (candidate_count) != ((selected_count).saturating_add(held_count)) {
        return Err("analyzer coverage candidate totals do not reconcile");
    }
    let unattributed_codes: Vec<String> = string_list(String::new(), String::from("analyzer coverage unattributed error codes"), 8_i64).unwrap_or_else(|_| Vec::new());
    if ((count(coverage.clone(), String::from("unattributed_error_count"), String::from("analyzer coverage")).unwrap_or_else(|_| 0_i64)) == (0_i64)) != ((((unattributed_codes.clone()).len() as i64)) == (0_i64)) {
        return Err("analyzer coverage unattributed error codes are inconsistent");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn publication_counts(mut value: String, mut label: String) -> Result<std::collections::BTreeMap<String, i64>, &'static str> {
    let root: std::collections::BTreeMap<String, String> = mapping(value.clone(), label.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn row_publication_counts(mut row: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, i64> {
    publication_counts(String::new(), String::from("analyzer coverage resource type publication counts")).unwrap_or_else(|_| std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn legacy_error_codes(mut row: std::collections::BTreeMap<String, String>, mut legacy: bool, mut label: String) -> Vec<String> {
    if legacy {
        return if (count(row.clone(), String::from("error_count"), format!("analyzer coverage {}", label.clone())).unwrap_or_else(|_| 0_i64)) > (0_i64) { vec![String::from("legacy_unspecified")] } else { Vec::<String>::new() };
    }
    string_list(String::new(), format!("analyzer coverage {} error codes", label.clone()), 8_i64).unwrap_or_else(|_| Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn count_mapping(mut value: String, mut label: String) -> Result<std::collections::BTreeMap<String, i64>, &'static str> {
    let root: std::collections::BTreeMap<String, String> = mapping(value.clone(), label.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    if (((root.clone()).len() as i64)) > (16_i64) {
        return Err("label is malformed");
    }
    let mut result: std::collections::BTreeMap<String, i64> = std::collections::BTreeMap::<String, i64>::new();
    for key in (root.clone()).into_keys() {
        if ((key.clone()).is_empty()) || ((((key.clone()).len() as i64)) > (128_i64)) {
            return Err("label is malformed");
        }
        let count: i64 = count(root.clone(), key.clone(), label.clone()).unwrap_or_else(|_| 0_i64);
        if (count) == (0_i64) {
            return Err("label is malformed");
        }
        result.insert(key.clone(), count);
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn string_list(mut value: String, mut label: String, mut maximum: i64) -> Result<Vec<String>, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn mapping(mut value: String, mut label: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if !(false) {
        return Err("label is malformed");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn sequence(mut value: String, mut label: String, mut maximum: i64) -> Result<Vec<String>, &'static str> {
    if (!(false)) || ((((value.clone()).len() as i64)) > (maximum)) {
        return Err("label is malformed");
    }
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn count(mut value: std::collections::BTreeMap<String, String>, mut key: String, mut label: String) -> Result<i64, &'static str> {
    let item: Option<String> = (value.clone()).get(key.as_str()).cloned();
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn text(mut value: String, mut label: String, mut maximum: i64) -> Result<String, &'static str> {
    if (!(true)) || (((value.clone()).is_empty()) || ((((value.clone()).len() as i64)) > (maximum))) {
        return Err("label is malformed");
    }
    Ok(value.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["project_analyzer_coverage", "unavailable_analyzer_coverage"];
