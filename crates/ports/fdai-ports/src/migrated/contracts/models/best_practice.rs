#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RequirementKind {
    #[default]
    Rule,
    Probe,
    Artifact,
    Metric,
    Drill,
    Approval,
}

impl RequirementKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Rule => "rule",
            Self::Probe => "probe",
            Self::Artifact => "artifact",
            Self::Metric => "metric",
            Self::Drill => "drill",
            Self::Approval => "approval",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RequirementMode {
    #[default]
    All,
    Any,
}

impl RequirementMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::All => "all",
            Self::Any => "any",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RequirementStatus {
    #[default]
    Satisfied,
    Failed,
    Unknown,
    NotApplicable,
}

impl RequirementStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Satisfied => "satisfied",
            Self::Failed => "failed",
            Self::Unknown => "unknown",
            Self::NotApplicable => "not_applicable",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BestPracticeRequirement {
    pub kind: RequirementKind,
    pub r#ref: String,
    pub freshness_days: Option<i64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RequirementOutcome {
    pub kind: RequirementKind,
    pub r#ref: String,
    pub status: RequirementStatus,
    pub scope: Option<String>,
    pub evidence_refs: Vec<String>,
    pub observed_at: Option<String>,
    pub recorded_at: Option<String>,
    pub source_identity: Option<String>,
    pub evidence_digest: Option<String>,
    pub not_applicable_reason: Option<String>,
    pub not_applicable_approved_by: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BestPractice {
    pub id: String,
    pub version: String,
    pub framework: String,
    pub control_id: String,
    pub title: String,
    pub rationale: String,
    pub severity: String,
    pub category: String,
    pub requirement_mode: RequirementMode,
    pub requirements: Vec<BestPracticeRequirement>,
    pub provenance: String,
}

impl RequirementOutcome {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_times_and_not_applicable_fields(&self) -> Result<String, &'static str> {
        Err("runtime_binding_required")
    }
}

impl BestPractice {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_requirement_keys(&self) -> Result<String, &'static str> {
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["BestPractice", "BestPracticeRequirement", "RequirementKind", "RequirementMode", "RequirementOutcome", "RequirementStatus"];
