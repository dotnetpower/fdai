#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn project_runtime_operational_state(mut value: String, mut read_now: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if !(false) {
        return Err("runtime operational state is malformed");
    }
    let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("source"), String::from("postgresql:state_kv")), (String::from("durable"), String::new()), (String::from("revision"), String::new()), (String::from("snapshot"), String::new())]);
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn project_runtime_model_scope(mut value: std::collections::BTreeMap<String, String>, mut snapshot: String, mut read_now: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    let scope_raw: Option<String> = (value.clone()).get("model_provider_scope").cloned();
    if scope_raw.is_some() {
    } else if ((value.clone()).get("model_provider_registration").cloned()).is_some() {
        return Err("model-provider scope is malformed");
    }
    Ok(result.clone())
}

