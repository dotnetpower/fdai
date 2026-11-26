#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InjectionMarkerError {
    pub message: String,
}

impl InjectionMarkerError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for InjectionMarkerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for InjectionMarkerError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn detect_injection_markers(mut body: String) -> Vec<String> {
    let mut hits: Vec<String> = Vec::<String>::new();
    hits.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn wrap_operator_note(mut body: String, mut author: String, mut scope_kind: String, mut scope_ref: String, mut category: String) -> String {
    if body.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn xml_escape(mut value: String) -> String {
    let mut escaped: String = value.clone();
    escaped.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn dedupe_preserving_order(mut items: Vec<String>) -> Vec<String> {
    let mut seen: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let mut out: Vec<String> = Vec::<String>::new();
    for item in items.clone() {
        if (seen.clone()).contains(item.as_str()) {
            continue;
        }
        seen.insert(item.clone());
        out.push(item.clone());
    }
    out.clone()
}

pub const PUBLIC_EXPORTS: &[&str] = &["InjectionMarkerError", "detect_injection_markers", "wrap_operator_note"];
