use std::collections::BTreeMap;
pub const UNRANKED: i64 = 99;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Priority {
    #[default]
    P1,
    P2,
    P3,
}

impl Priority {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::P1 => "p1",
            Self::P2 => "p2",
            Self::P3 => "p3",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum InvestigationOutcome {
    #[default]
    Completed,
    Partial,
    BudgetExceeded,
    Abstained,
}

impl InvestigationOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Completed => "completed",
            Self::Partial => "partial",
            Self::BudgetExceeded => "budget_exceeded",
            Self::Abstained => "abstained",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnalyzerFinding {
    pub resource_ref: String,
    pub resource_kind: String,
    pub signal: String,
    pub observation: String,
    pub severity: String,
    pub occurred_at: String,
    pub evidence_refs: Vec<String>,
    pub remediation_ref: Option<String>,
    pub metadata: BTreeMap<String, String>,
    #[allow(clippy::type_complexity)]
    pub assessment: Option<Box<FindingAssessment>>,
}

impl AnalyzerFinding {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.resource_ref.trim().is_empty() { return Err("resource_ref must be non-empty"); }
        if self.resource_kind.trim().is_empty() { return Err("resource_kind must be non-empty"); }
        if self.signal.trim().is_empty() { return Err("signal must be non-empty"); }
        if self.observation.trim().is_empty() { return Err("observation must be non-empty"); }
        if self.severity.trim().is_empty() { return Err("severity must be non-empty"); }
        if self.occurred_at.trim().is_empty() { return Err("occurred_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FindingAssessment {
    pub assessed_by: String,
    pub evidence_complete: bool,
    pub recovery_closed: Option<bool>,
    pub status: String,
    pub recovery_status: Option<String>,
    pub evidence_gaps: Vec<String>,
}

impl FindingAssessment {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.assessed_by.trim().is_empty() { return Err("assessed_by must be non-empty"); }
        if self.status.trim().is_empty() { return Err("status must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TimelineEntry {
    pub occurred_at: String,
    pub resource_ref: String,
    pub resource_kind: String,
    pub description: String,
    pub severity: String,
}

impl TimelineEntry {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.occurred_at.trim().is_empty() { return Err("occurred_at must be non-empty"); }
        if self.resource_ref.trim().is_empty() { return Err("resource_ref must be non-empty"); }
        if self.resource_kind.trim().is_empty() { return Err("resource_kind must be non-empty"); }
        if self.description.trim().is_empty() { return Err("description must be non-empty"); }
        if self.severity.trim().is_empty() { return Err("severity must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Recommendation {
    pub priority: Priority,
    pub title: String,
    pub detail: String,
    pub resource_ref: String,
    pub remediation_ref: Option<String>,
    pub citations: Vec<String>,
}

impl Recommendation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.title.trim().is_empty() { return Err("title must be non-empty"); }
        if self.detail.trim().is_empty() { return Err("detail must be non-empty"); }
        if self.resource_ref.trim().is_empty() { return Err("resource_ref must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InvestigationReport {
    pub investigation_id: String,
    pub requested_by: String,
    pub requested_at: String,
    pub window_seconds: f64,
    pub resources: Vec<String>,
    pub outcome: InvestigationOutcome,
    pub findings: Vec<AnalyzerFinding>,
    pub timeline: Vec<TimelineEntry>,
    pub correlation: Vec<String>,
    pub root_cause: Option<String>,
    pub recommendations: Vec<Recommendation>,
    pub elapsed_seconds: f64,
    pub budget_seconds: f64,
    pub analyzer_errors: Vec<String>,
}

impl InvestigationReport {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.investigation_id.trim().is_empty() { return Err("investigation_id must be non-empty"); }
        if self.requested_by.trim().is_empty() { return Err("requested_by must be non-empty"); }
        if self.requested_at.trim().is_empty() { return Err("requested_at must be non-empty"); }
        Ok(())
    }
}

impl FindingAssessment {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("assessed_by"), self.assessed_by.clone()), (String::from("evidence_complete"), String::new()), (String::from("recovery_closed"), String::new()), (String::from("status"), self.status.clone()), (String::from("recovery_status"), (self.recovery_status.clone()).unwrap_or_default()), (String::from("evidence_gaps"), String::new())])
    }
}

impl InvestigationReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn within_budget(&self) -> bool {
        (self.elapsed_seconds) <= (self.budget_seconds)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn resource_count(&self) -> i64 {
        (self.resources.clone()).len() as i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn kpi(&self) -> std::collections::BTreeMap<String, f64> {
        std::collections::BTreeMap::from([(String::from("investigation.latency_seconds"), self.elapsed_seconds), (String::from("investigation.budget_seconds"), self.budget_seconds), (String::from("investigation.within_budget"), 0.0_f64), (String::from("investigation.resource_count"), 0.0_f64), (String::from("investigation.finding_count"), ((((self.findings.clone()).len() as i64)) as f64)), (String::from("investigation.recommendation_count"), ((((self.recommendations.clone()).len() as i64)) as f64))])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn priority_for(mut severity: String) -> Priority {
    if severity.is_empty() {
        return Default::default();
    }
    Default::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn priority_rank(mut priority: Priority) -> i64 {
    0_i64
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn severity_rank(mut severity: String) -> i64 {
    0_i64
}

pub const PUBLIC_EXPORTS: &[&str] = &["AnalyzerFinding", "FindingAssessment", "InvestigationOutcome", "InvestigationReport", "Priority", "Recommendation", "TimelineEntry", "priority_for", "priority_rank", "severity_rank"];
