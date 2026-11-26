use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum InventoryObservationKind {
    #[default]
    Observed,
    Expected,
}

impl InventoryObservationKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Observed => "observed",
            Self::Expected => "expected",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum InventoryFailureCode {
    #[default]
    NetworkBlocked,
    DnsFailed,
    TokenFailed,
    Forbidden,
    Throttled,
    Partial,
    SourceUnavailable,
    InvalidData,
}

impl InventoryFailureCode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::NetworkBlocked => "network_blocked",
            Self::DnsFailed => "dns_failed",
            Self::TokenFailed => "token_failed",
            Self::Forbidden => "forbidden",
            Self::Throttled => "throttled",
            Self::Partial => "partial",
            Self::SourceUnavailable => "source_unavailable",
            Self::InvalidData => "invalid_data",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryCoverageManifest {
    pub source: String,
    pub scopes: Vec<String>,
    pub resource_types: Vec<String>,
    pub observation_kind: InventoryObservationKind,
    pub started_at: Option<String>,
    pub completed_at: Option<String>,
    pub metadata: BTreeMap<String, String>,
}

impl InventoryCoverageManifest {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.source.trim().is_empty() { return Err("source must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryAttemptFailure {
    pub code: InventoryFailureCode,
    pub message: String,
}

impl InventoryAttemptFailure {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.message.trim().is_empty() { return Err("message must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventorySource {
    pub name: String,
    pub inventory: String,
    pub manifest: Box<InventoryCoverageManifest>,
}

impl InventorySource {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.name.trim().is_empty() { return Err("name must be non-empty"); }
        if self.inventory.trim().is_empty() { return Err("inventory must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventorySyncResult {
    pub attempt_id: String,
    pub source: String,
    pub failures: Vec<InventoryAttemptFailure>,
}

pub trait InventorySnapshotStore {
    fn begin(&self, manifest: InventoryCoverageManifest) -> String;
    fn stage(&self, attempt_id: String, batch: String);
    fn promote(&self, attempt_id: String, manifest: InventoryCoverageManifest);
    fn fail(&self, attempt_id: String, failure: InventoryAttemptFailure);
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InventorySourcesExhaustedError {
    pub message: String,
}

impl InventorySourcesExhaustedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for InventorySourcesExhaustedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for InventorySourcesExhaustedError {}

pub const PUBLIC_EXPORTS: &[&str] = &["InventoryAttemptFailure", "InventoryCoverageManifest", "InventoryFailureCode", "InventoryObservationKind", "InventorySnapshotStore", "InventorySource", "InventorySourcesExhaustedError", "InventorySyncResult"];
