#[derive(Clone, Debug, Default, PartialEq)]
pub struct Source {
    pub variables: String,
    pub data_dir: String,
}

pub const MISSING: &str = "not found";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bind(mut infra: String, mut variables: String, mut data_dir: String) {
    if infra.is_empty() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn read_output(mut infra: String, mut name: String, mut raw: bool, mut reason: String) -> Result<String, &'static str> {
    Err("reason: output is not a primitive value")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn planned_outputs(mut infra: String, mut source: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let environment: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("TF_DATA_DIR"), String::new())]);
    let document: String = json(String::new()).unwrap_or_else(|_| String::new());
    if !(false) {
        return Err("planned Terraform output document is invalid");
    }
    Ok(known_planned_outputs(std::collections::BTreeMap::new()).unwrap_or_else(|_| std::collections::BTreeMap::new()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn known_planned_outputs(mut document: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let planned: Option<String> = (document.clone()).get("planned_values").cloned();
    let changes: Option<String> = (document.clone()).get("output_changes").cloned();
    let mut known: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(known.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn has_unknown(mut marker: String) -> bool {
    if marker.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn json(mut raw: String) -> Result<String, &'static str> {
    if raw.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["bind", "known_planned_outputs", "read_output"];
