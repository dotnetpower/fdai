use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct PreflightCheck {
    pub pr_ref: String,
    pub check_key: String,
    pub report: String,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PreflightCheckReceipt {
    pub check_ref: String,
    pub url: Option<String>,
    pub already_existed: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PreflightCheckPublishError {
    pub message: String,
}

impl PreflightCheckPublishError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for PreflightCheckPublishError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PreflightCheckPublishError {}

pub trait PreflightCheckPublisher {
    fn publish(&self, check: PreflightCheck) -> PreflightCheckReceipt;
}

pub const PUBLIC_EXPORTS: &[&str] = &["PreflightCheck", "PreflightCheckPublishError", "PreflightCheckPublisher", "PreflightCheckReceipt"];
