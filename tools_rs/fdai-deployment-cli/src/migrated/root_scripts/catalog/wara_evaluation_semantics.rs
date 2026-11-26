#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn field(mut path: String, mut kind: String, mut constraints: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("path"), path.clone()), (String::from("value_type"), kind.clone())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn choices(mut path: String, mut values: Vec<String>) -> std::collections::BTreeMap<String, String> {
    field(path.clone(), String::new(), std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn array(mut path: String, mut minimum: i64) -> std::collections::BTreeMap<String, String> {
    let mut constraints: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("minimum_items"), String::new())]);
    field(path.clone(), String::from("array"), std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn boolean(mut path: String, mut expected: Option<bool>) -> std::collections::BTreeMap<String, String> {
    field(path.clone(), String::from("boolean"), std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn regional(mut requirements: Vec<String>) -> (bool, Vec<std::collections::BTreeMap<String, String>>) {
    (false, Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn every(mut requirements: Vec<String>) -> (bool, Vec<std::collections::BTreeMap<String, String>>) {
    (false, Vec::new())
}

