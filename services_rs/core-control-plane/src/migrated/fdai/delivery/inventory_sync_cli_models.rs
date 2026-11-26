#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryJobResult {
    pub attempt_id: String,
    pub source: String,
    pub active: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChangeStreamDrainResult {
    pub published: i64,
    pub unavailable_sources: Vec<String>,
}

impl ChangeStreamDrainResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn degraded(&self) -> bool {
        !(self.unavailable_sources.clone()).is_empty()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InventoryOntologyProjectionIncompleteError {
    pub message: String,
}

impl InventoryOntologyProjectionIncompleteError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for InventoryOntologyProjectionIncompleteError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for InventoryOntologyProjectionIncompleteError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn scope_ref(mut scopes: Vec<String>) -> String {
    if scopes.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn generation_digest(mut generation: String) -> String {
    if generation.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ChangeStreamDrainResult", "InventoryJobResult", "InventoryOntologyProjectionIncompleteError", "generation_digest", "scope_ref"];
