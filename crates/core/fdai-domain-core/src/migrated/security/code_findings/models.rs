#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Lane {
    #[default]
    Deterministic,
    LlmLens,
    External,
}

impl Lane {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Deterministic => "deterministic",
            Self::LlmLens => "llm_lens",
            Self::External => "external",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SeverityMethod {
    #[default]
    FactRubric,
    AdvisoryScore,
}

impl SeverityMethod {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::FactRubric => "fact_rubric",
            Self::AdvisoryScore => "advisory_score",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TestFeasibility {
    #[default]
    Available,
    NoHarness,
    Unknown,
}

impl TestFeasibility {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Available => "available",
            Self::NoHarness => "no_harness",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SourceLocation {
    pub path: String,
    pub start_line: Option<i64>,
    pub end_line: Option<i64>,
    pub symbol: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FlowStep {
    pub path: String,
    pub line: Option<i64>,
    pub kind: String,
    pub end_line: Option<i64>,
    pub node_id: Option<String>,
    pub call_context: Vec<String>,
}

impl FlowStep {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "source" | "flow" | "call" | "return" | "sanitizer" | "sink") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnalysisPathEvidence {
    pub path_id: String,
    pub path_digest: String,
    pub graph_digest: String,
    pub graph_schema_version: String,
    pub path_schema_version: String,
    pub rule_version: String,
    pub frontend_versions: Vec<String>,
    pub coverage_limits: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Occurrence {
    pub occurrence_id: String,
    pub producer: String,
    pub producer_version: String,
    pub lane: Lane,
    pub scan_digest: String,
    pub revision: String,
    pub rule_id: String,
    pub location: Box<SourceLocation>,
    pub cwe_ids: Vec<i64>,
    pub tags: Vec<String>,
    pub source_severity: String,
    pub message: String,
    pub code_flow: Vec<FlowStep>,
    pub advisory_ids: Vec<String>,
    pub package: Option<String>,
    pub package_version: Option<String>,
    pub advisory_score: Option<f64>,
    pub fingerprints: Vec<String>,
    #[allow(clippy::type_complexity)]
    pub analysis_evidence: Option<Box<AnalysisPathEvidence>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InstanceFacts {
    pub impact: Option<String>,
    pub attack_vector: Option<String>,
    pub attack_complexity: Option<String>,
    pub privileges_required: Option<String>,
    pub user_interaction: Option<String>,
    pub evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SeverityAssessment {
    pub label: String,
    pub floor: String,
    pub ceiling: String,
    pub method: SeverityMethod,
    pub floor_points: f64,
    pub ceiling_points: f64,
    pub unknown_facts: Vec<String>,
    pub deciding_facts: Vec<String>,
    pub rationale: String,
    pub rubric_version: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Instance {
    pub instance_id: String,
    #[allow(clippy::type_complexity)]
    pub source: Option<Box<FlowStep>>,
    pub occurrence_ids: Vec<String>,
    pub facts: Box<InstanceFacts>,
    pub severity: Box<SeverityAssessment>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PriorityAssignment {
    pub priority: String,
    pub due_days: i64,
    pub rule_id: String,
    pub policy_version: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CodeSecurityIssue {
    pub issue_id: String,
    pub weakness_class: String,
    pub title: String,
    pub revision: String,
    pub fix_site: Box<SourceLocation>,
    pub severity: Box<SeverityAssessment>,
    pub governing_instance_id: String,
    pub confidence: String,
    pub exposure: String,
    pub priority: Box<PriorityAssignment>,
    pub instances: Vec<Instance>,
    pub cwe_ids: Vec<i64>,
    pub producers: Vec<String>,
    pub lanes: Vec<Lane>,
    pub occurrence_ids: Vec<String>,
    pub source_severities: Vec<String>,
    pub advisory_ids: Vec<String>,
    pub package: Option<String>,
    pub package_versions: Vec<String>,
    pub layers: Vec<String>,
    pub known_exploited: bool,
    pub code_flow: Vec<FlowStep>,
    pub messages: Vec<String>,
    #[allow(clippy::type_complexity)]
    pub analysis_evidence: Option<Box<AnalysisPathEvidence>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProjectRoot {
    pub path: String,
    pub ecosystem: String,
    pub targeted_test_command: Option<String>,
    pub full_test_command: Option<String>,
    pub generator_command: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FixGroup {
    pub group_id: String,
    pub title: String,
    pub weakness_class: String,
    pub fix_class: String,
    pub autofix_eligibility: String,
    pub max_depth: String,
    pub priority: String,
    pub issue_ids: Vec<String>,
    pub allowed_paths: Vec<String>,
    pub guidance: String,
    pub project_root: String,
    pub ecosystem: String,
    pub targeted_test_command: Option<String>,
    pub full_test_command: Option<String>,
    pub test_feasibility: TestFeasibility,
    pub order: i64,
}

pub const UNDETERMINED: &str = "undetermined";
impl SeverityAssessment {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn determined(&self) -> bool {
        (self.label.clone()) != (String::from(UNDETERMINED))
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["UNDETERMINED", "AnalysisPathEvidence", "CodeSecurityIssue", "FixGroup", "FlowStep", "Instance", "InstanceFacts", "Lane", "Occurrence", "PriorityAssignment", "ProjectRoot", "SeverityAssessment", "SeverityMethod", "SourceLocation", "TestFeasibility"];
