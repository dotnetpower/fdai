#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ControlStatus {
    #[default]
    Pass,
    Fail,
    Warning,
    NotApplicable,
    Unknown,
}

impl ControlStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pass => "pass",
            Self::Fail => "fail",
            Self::Warning => "warning",
            Self::NotApplicable => "not_applicable",
            Self::Unknown => "unknown",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SourceStatus {
    #[default]
    Available,
    Partial,
    Unavailable,
}

impl SourceStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Available => "available",
            Self::Partial => "partial",
            Self::Unavailable => "unavailable",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ApplicabilityStatus {
    #[default]
    Applicable,
    NotApplicable,
    Unknown,
}

impl ApplicabilityStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Applicable => "applicable",
            Self::NotApplicable => "not_applicable",
            Self::Unknown => "unknown",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RemediationPriority {
    #[default]
    Critical,
    High,
    Medium,
    Low,
    None,
}

impl RemediationPriority {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Critical => "critical",
            Self::High => "high",
            Self::Medium => "medium",
            Self::Low => "low",
            Self::None => "none",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SecurityControlObservation {
    pub control_id: String,
    pub title: String,
    pub category: String,
    pub resource_type: String,
    pub resource_ref: String,
    pub status: ControlStatus,
    pub severity: String,
    pub current_value: String,
    pub expected_value: String,
    pub rationale: String,
    pub source: String,
    pub collected_at: String,
    pub evidence_refs: Vec<String>,
    pub remediation: String,
    pub validation: String,
    pub priority: RemediationPriority,
    pub due_days: Option<i64>,
    pub applicability: ApplicabilityStatus,
    pub cve_ids: Vec<String>,
    pub compliance_controls: Vec<String>,
    pub source_urls: Vec<String>,
    pub managed_service_note: String,
    pub patch_status: String,
}

impl SecurityControlObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.control_id.trim().is_empty() { return Err("control_id must be non-empty"); }
        if self.title.trim().is_empty() { return Err("title must be non-empty"); }
        if self.category.trim().is_empty() { return Err("category must be non-empty"); }
        if self.resource_type.trim().is_empty() { return Err("resource_type must be non-empty"); }
        if self.resource_ref.trim().is_empty() { return Err("resource_ref must be non-empty"); }
        if self.severity.trim().is_empty() { return Err("severity must be non-empty"); }
        if self.current_value.trim().is_empty() { return Err("current_value must be non-empty"); }
        if self.expected_value.trim().is_empty() { return Err("expected_value must be non-empty"); }
        if self.rationale.trim().is_empty() { return Err("rationale must be non-empty"); }
        if self.source.trim().is_empty() { return Err("source must be non-empty"); }
        if self.collected_at.trim().is_empty() { return Err("collected_at must be non-empty"); }
        if self.remediation.trim().is_empty() { return Err("remediation must be non-empty"); }
        if self.validation.trim().is_empty() { return Err("validation must be non-empty"); }
        if self.managed_service_note.trim().is_empty() { return Err("managed_service_note must be non-empty"); }
        if self.patch_status.trim().is_empty() { return Err("patch_status must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SecuritySourceCoverage {
    pub source: String,
    pub status: SourceStatus,
    pub record_count: i64,
    pub as_of: Option<String>,
    pub scope: String,
    pub error: String,
    pub fresh: Option<bool>,
}

impl SecuritySourceCoverage {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.source.trim().is_empty() { return Err("source must be non-empty"); }
        if self.scope.trim().is_empty() { return Err("scope must be non-empty"); }
        if self.error.trim().is_empty() { return Err("error must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SecurityRecommendation {
    pub control_id: String,
    pub resource_ref: String,
    pub priority: RemediationPriority,
    pub severity: String,
    pub action: String,
    pub validation: String,
    pub due_at: Option<String>,
    pub evidence_refs: Vec<String>,
}

pub const PUBLIC_EXPORTS: &[&str] = &["ControlStatus", "ApplicabilityStatus", "RemediationPriority", "SecurityControlObservation", "SecurityRecommendation", "SecuritySourceCoverage", "SourceStatus"];
