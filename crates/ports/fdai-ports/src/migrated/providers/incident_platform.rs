#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ExternalIncidentStatus {
    #[default]
    Triggered,
    Acknowledged,
    Resolved,
}

impl ExternalIncidentStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Triggered => "triggered",
            Self::Acknowledged => "acknowledged",
            Self::Resolved => "resolved",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExternalIncident {
    pub platform: String,
    pub incident_ref: String,
    pub title: String,
    pub severity: String,
    pub status: ExternalIncidentStatus,
    pub created_at: String,
    pub updated_at: String,
    pub service_ref: Option<String>,
    pub source_url: Option<String>,
}

impl ExternalIncident {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.platform.trim().is_empty() { return Err("platform must be non-empty"); }
        if self.incident_ref.trim().is_empty() { return Err("incident_ref must be non-empty"); }
        if self.title.trim().is_empty() { return Err("title must be non-empty"); }
        if self.severity.trim().is_empty() { return Err("severity must be non-empty"); }
        if self.created_at.trim().is_empty() { return Err("created_at must be non-empty"); }
        if self.updated_at.trim().is_empty() { return Err("updated_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct IncidentPlatformError {
    pub message: String,
}

impl IncidentPlatformError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for IncidentPlatformError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for IncidentPlatformError {}

pub trait IncidentPlatform {
    fn list_active(&self, limit: i64) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["ExternalIncident", "ExternalIncidentStatus", "IncidentPlatform", "IncidentPlatformError"];
