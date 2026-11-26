#[derive(Clone, Debug, Default, PartialEq)]
pub struct BestPracticeLoadIssue {
    pub key: String,
    pub message: String,
}

pub const SCHEMA_PACKAGE: &str = "fdai.rule_catalog.schema";
pub const SCHEMA_FILE: &str = "best_practice.schema.json";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BestPracticeLoadError {
    pub message: String,
}

impl BestPracticeLoadError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for BestPracticeLoadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for BestPracticeLoadError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn validator() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_best_practice_from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    if raw.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["BestPracticeLoadError", "BestPracticeLoadIssue", "load_best_practice_from_mapping"];
