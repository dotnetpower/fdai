#[derive(Clone, Debug, Default, PartialEq)]
pub struct LensModelIdentity {
    pub family: String,
    pub deployment: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LensRequest {
    pub lens_id: String,
    pub focus: String,
    pub cwe: Vec<i64>,
    pub language: String,
    pub path: String,
    pub first_line: i64,
    pub last_line: i64,
    pub numbered_excerpt: String,
    pub max_findings: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LensFinding {
    pub line: i64,
    pub cwe: i64,
    pub confidence: String,
    pub explanation: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LensResponse {
    pub findings: Vec<LensFinding>,
    pub model: Box<LensModelIdentity>,
    pub prompt_tokens: i64,
    pub completion_tokens: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LensModelError {
    pub message: String,
}

impl LensModelError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for LensModelError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for LensModelError {}

pub trait CodeSecurityLensModel {
    fn identity(&self) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["CodeSecurityLensModel", "LensFinding", "LensModelError", "LensModelIdentity", "LensRequest", "LensResponse"];
