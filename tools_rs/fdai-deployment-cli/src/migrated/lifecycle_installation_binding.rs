pub const MAX_BINDING_VALUES: i64 = 128;
pub const MAX_BINDING_VALUE_LENGTH: i64 = 1024;

pub const INSTALLATION_BINDING_FORMAT: &str = "fdai.installation-binding.v1";
pub const BINDING_KEY: &str = "[a-z][a-z0-9_.-]{0,62}\\Z";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_installation_binding_values(mut values: std::collections::BTreeMap<String, String>, mut allowed_keys: std::collections::BTreeSet<String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if (((values.clone()).len() as i64)) > (MAX_BINDING_VALUES) {
        return Err("installation binding has too many values");
    }
    let mut validated: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    for (key, value) in values.clone() {
        validated.insert(key.clone(), value.clone());
    }
    Ok(validated.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn write_installation_binding(mut path: String, mut values: std::collections::BTreeMap<String, String>, mut allowed_keys: std::collections::BTreeSet<String>) {
    let validated: std::collections::BTreeMap<String, String> = validate_installation_binding_values(values.clone(), allowed_keys.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let document: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("format"), String::from(INSTALLATION_BINDING_FORMAT)), (String::from("values"), String::new())]);
}

