#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn runtime_relationship(mut request: String, mut now: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("verified_relationship"), String::new()), (String::from("relationship_proof"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn unknown(mut request: String, mut reason: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("relationship_status"), String::from("unknown")), (String::from("relationship_unknown_reason"), reason.clone())])
}

