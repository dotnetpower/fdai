#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn raw_installation_public_key(mut key: String) -> Vec<u8> {
    if key.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn installation_key_id(mut public_key: Vec<u8>) -> String {
    if public_key.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn sign_enrollment_payload(mut template: std::collections::BTreeMap<String, String>, mut key: String, mut at: String) -> Result<(Vec<u8>, Vec<u8>), &'static str> {
    let fields: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("installation_key"), String::new()), (String::from("requested_at"), String::new())]);
    Ok((Vec::new(), Vec::new()))
}

