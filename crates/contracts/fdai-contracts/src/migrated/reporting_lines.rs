#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReportingLineExtractionSource {
    #[default]
    Deterministic,
    Model,
}

impl ReportingLineExtractionSource {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Deterministic => "deterministic",
            Self::Model => "model",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReportingLineDirectoryComparison {
    #[default]
    Matched,
    Conflict,
    Unavailable,
    NotChecked,
}

impl ReportingLineDirectoryComparison {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Matched => "matched",
            Self::Conflict => "conflict",
            Self::Unavailable => "unavailable",
            Self::NotChecked => "not_checked",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReportingLineDraftOutcome {
    #[default]
    Drafted,
    Abstained,
}

impl ReportingLineDraftOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Drafted => "drafted",
            Self::Abstained => "abstained",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReportingLineManagerStatus {
    #[default]
    Resolved,
    NotFound,
    Unavailable,
}

impl ReportingLineManagerStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Resolved => "resolved",
            Self::NotFound => "not_found",
            Self::Unavailable => "unavailable",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportingLineSourceSpan {
    pub unit_id: String,
    pub locator: String,
    pub quote: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportingLinePerson {
    pub display_name: String,
    pub oid: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportingLineResolvedIdentity {
    pub oid: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportingLineManagerObservation {
    pub status: ReportingLineManagerStatus,
    pub manager_oid: Option<String>,
    pub observed_at: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportingLineCandidate {
    pub candidate_id: String,
    pub subject: Box<ReportingLinePerson>,
    pub manager: Box<ReportingLinePerson>,
    pub relationship_kind: String,
    pub effective_from: Option<String>,
    pub effective_until: Option<String>,
    pub confidence: f64,
    pub extraction_source: ReportingLineExtractionSource,
    pub citations: Vec<ReportingLineSourceSpan>,
    pub directory_manager_oid: Option<String>,
    pub directory_comparison: ReportingLineDirectoryComparison,
}

impl ReportingLineCandidate {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.relationship_kind.as_str(), "primary_manager") { return Err("invalid relationship_kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportingLineDraftArtifact {
    pub schema_version: String,
    pub upload_id: String,
    pub document_id: String,
    pub version_id: String,
    pub source_sha256: String,
    pub outcome: ReportingLineDraftOutcome,
    pub candidates: Vec<ReportingLineCandidate>,
    pub abstained: Vec<ReportingLineCandidate>,
    pub unresolved_people: Vec<ReportingLinePerson>,
    pub warnings: Vec<String>,
}

impl ReportingLineDraftArtifact {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReportingLineContract {
    pub initialized: bool,
}

impl ReportingLineManagerObservation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn consistent(&self) -> Result<ReportingLineManagerObservation, &'static str> {
        Err("runtime_binding_required")
    }
}

pub trait ReportingLineDirectory {
    fn resolve(&self, display_name: String) -> String;
}

impl ReportingLineCandidate {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_candidate(&self) -> Result<ReportingLineCandidate, &'static str> {
        if (self.effective_from.is_some()) && ((self.effective_until.is_some()) && (((self.effective_from.clone()).unwrap_or_default()) >= ((self.effective_until.clone()).unwrap_or_default()))) {
            return Err("reporting-line effective window MUST be non-empty");
        }
        let expected: String = reporting_line_candidate_id(*(self.subject.clone()), *(self.manager.clone()), self.relationship_kind.clone(), self.effective_from.clone(), self.effective_until.clone(), self.citations.clone());
        if (self.candidate_id.clone()) != (expected.clone()) {
            return Err("reporting-line candidate identity does not match its content");
        }
        Ok(self.clone())
    }
}

impl ReportingLineDraftArtifact {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_outcome(&self) -> Result<ReportingLineDraftArtifact, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::new()
    }
}

pub trait ReportingLineDraftStore {
    fn put(&self, artifact: ReportingLineDraftArtifact) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn reporting_line_candidate_id(mut subject: ReportingLinePerson, mut manager: ReportingLinePerson, mut relationship_kind: String, mut effective_from: Option<String>, mut effective_until: Option<String>, mut citations: Vec<ReportingLineSourceSpan>) -> String {
    let material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("subject"), String::new()), (String::from("manager"), String::new()), (String::from("relationship_kind"), relationship_kind.clone()), (String::from("effective_from"), String::new()), (String::from("effective_until"), String::new()), (String::from("citations"), String::new())]);
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ReportingLineCandidate", "ReportingLineDirectoryComparison", "ReportingLineDirectory", "ReportingLineDraftArtifact", "ReportingLineDraftOutcome", "ReportingLineDraftStore", "ReportingLineExtractionSource", "ReportingLineManagerObservation", "ReportingLineManagerStatus", "ReportingLinePerson", "ReportingLineResolvedIdentity", "ReportingLineSourceSpan", "reporting_line_candidate_id"];
