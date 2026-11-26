use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct RunbookResult {
    pub ok: bool,
    pub summary: String,
    pub detail: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RunbookError {
    pub message: String,
}

impl RunbookError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for RunbookError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for RunbookError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RunbookNotFoundError {
    pub message: String,
}

impl RunbookNotFoundError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for RunbookNotFoundError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for RunbookNotFoundError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RunbookExecutionError {
    pub message: String,
}

impl RunbookExecutionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for RunbookExecutionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for RunbookExecutionError {}

pub trait RunbookRegistry {
    fn names(&self) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["RunbookError", "RunbookExecutionError", "RunbookNotFoundError", "RunbookRegistry", "RunbookResult"];
