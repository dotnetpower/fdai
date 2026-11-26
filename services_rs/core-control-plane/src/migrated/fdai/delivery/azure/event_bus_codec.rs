pub const MAX_RAW_ERROR_CHARS: i64 = 4096;

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn encode_payload(mut payload: std::collections::BTreeMap<String, String>) -> Vec<u8> {
    if payload.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn decode_payload(mut value: Option<Vec<u8>>, mut topic: String, mut key: String) -> std::collections::BTreeMap<String, String> {
    let Some(mut value) = value.clone() else { return std::collections::BTreeMap::<String, String>::new(); };
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn decode_key(mut value: Option<Vec<u8>>) -> String {
    let Some(mut value) = value.clone() else { return String::from(""); };
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["decode_key", "decode_payload", "encode_payload"];
