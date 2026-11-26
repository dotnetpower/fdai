use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum GraphNodeKind {
    #[default]
    File,
    Function,
    Symbol,
    CallSite,
    BasicBlock,
    DataFlow,
    Source,
    Sink,
    Sanitizer,
}

impl GraphNodeKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::File => "file",
            Self::Function => "function",
            Self::Symbol => "symbol",
            Self::CallSite => "call_site",
            Self::BasicBlock => "basic_block",
            Self::DataFlow => "data_flow",
            Self::Source => "source",
            Self::Sink => "sink",
            Self::Sanitizer => "sanitizer",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum GraphEdgeKind {
    #[default]
    Declares,
    Calls,
    Controls,
    Defines,
    Uses,
    FlowsTo,
    ArgumentTo,
    ReturnsTo,
    Aliases,
    SanitizesFor,
}

impl GraphEdgeKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Declares => "declares",
            Self::Calls => "calls",
            Self::Controls => "controls",
            Self::Defines => "defines",
            Self::Uses => "uses",
            Self::FlowsTo => "flows_to",
            Self::ArgumentTo => "argument_to",
            Self::ReturnsTo => "returns_to",
            Self::Aliases => "aliases",
            Self::SanitizesFor => "sanitizes_for",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EvidenceConfidence {
    #[default]
    Exact,
    Inferred,
    Unresolved,
}

impl EvidenceConfidence {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Exact => "exact",
            Self::Inferred => "inferred",
            Self::Unresolved => "unresolved",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RuleAnalysisKind {
    #[default]
    Ast,
    Typed,
    GraphFlow,
}

impl RuleAnalysisKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Ast => "ast",
            Self::Typed => "typed",
            Self::GraphFlow => "graph_flow",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PathStepRole {
    #[default]
    Source,
    Flow,
    Call,
    Return,
    Sanitizer,
    Sink,
}

impl PathStepRole {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Source => "source",
            Self::Flow => "flow",
            Self::Call => "call",
            Self::Return => "return",
            Self::Sanitizer => "sanitizer",
            Self::Sink => "sink",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SourceSpan {
    pub path: String,
    pub start_line: i64,
    pub start_column: i64,
    pub end_line: i64,
    pub end_column: i64,
}

impl SourceSpan {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=9223372036854775807_i64).contains(&self.start_line) { return Err("start_line out of bounds"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.start_column) { return Err("start_column out of bounds"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.end_line) { return Err("end_line out of bounds"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.end_column) { return Err("end_column out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnalysisProvenance {
    pub frontend: String,
    pub frontend_version: String,
    pub model_version: String,
    pub confidence: EvidenceConfidence,
    pub unresolved_alternatives: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CodeGraphNode {
    pub node_id: String,
    pub kind: GraphNodeKind,
    pub name: String,
    #[allow(clippy::type_complexity)]
    pub span: Option<Box<SourceSpan>>,
    pub type_status: String,
    pub type_name: Option<String>,
}

impl CodeGraphNode {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.type_status.as_str(), "resolved" | "partial" | "unknown") { return Err("invalid type_status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CodeGraphEdge {
    pub edge_id: String,
    pub kind: GraphEdgeKind,
    pub source_id: String,
    pub target_id: String,
    pub provenance: Box<AnalysisProvenance>,
    pub parameter_index: Option<i64>,
    pub security_context: Option<String>,
    pub source_role: Option<PathStepRole>,
    pub target_role: Option<PathStepRole>,
    pub source_context: Vec<String>,
    pub target_context: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CodeGraphArtifact {
    pub schema_version: String,
    pub revision: String,
    pub build_context_digest: String,
    pub framework_model_digest: String,
    pub frontend_versions: BTreeMap<String, String>,
    pub nodes: Vec<CodeGraphNode>,
    pub edges: Vec<CodeGraphEdge>,
    pub coverage_limits: Vec<String>,
}

impl CodeGraphArtifact {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.1.0") { return Err("invalid schema_version literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleSelector {
    pub role: String,
    pub symbol: String,
    pub argument_index: Option<i64>,
    pub security_context: Option<String>,
}

impl RuleSelector {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.role.as_str(), "source" | "sink" | "propagator" | "sanitizer") { return Err("invalid role literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CodeSecurityRuleSpec {
    pub schema_version: String,
    pub rule_id: String,
    pub version: String,
    pub analysis_kind: RuleAnalysisKind,
    pub languages: Vec<String>,
    pub cwe_ids: Vec<i64>,
    pub selectors: Vec<RuleSelector>,
    pub vulnerable_cases: Vec<String>,
    pub safe_cases: Vec<String>,
}

impl CodeSecurityRuleSpec {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PathEvidenceStep {
    pub node_id: String,
    pub role: PathStepRole,
    pub span: Box<SourceSpan>,
    pub call_context: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PathEvidence {
    pub schema_version: String,
    pub path_id: String,
    pub revision: String,
    pub graph_digest: String,
    pub rule_id: String,
    pub rule_version: String,
    pub steps: Vec<PathEvidenceStep>,
    pub sanitizers_considered: Vec<String>,
    pub coverage_limits: Vec<String>,
}

impl PathEvidence {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.1.0") { return Err("invalid schema_version literal"); }
        Ok(())
    }
}

pub const ID_PATTERN: &str = "^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$";
pub const DIGEST_PATTERN: &str = "^sha256:[a-f0-9]{64}$";
pub const REVISION_PATTERN: &str = "^[a-f0-9]{40,64}$";
pub const VERSION_PATTERN: &str = "^\\d+\\.\\d+\\.\\d+$";
pub const DOTTED_PATTERN: &str = "^[A-Za-z_$][A-Za-z0-9_$]*(\\.[A-Za-z_$][A-Za-z0-9_$]*)*$";
pub const GRAPH_SCHEMA_VERSION: &str = "1.1.0";
pub const PATH_SCHEMA_VERSION: &str = "1.1.0";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StrictModel {
    pub initialized: bool,
}

impl StrictModel {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn canonical_bytes(&self) -> Vec<u8> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

impl SourceSpan {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn relative_path(mut value: String) -> Result<String, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn ordered(&self) -> Result<SourceSpan, &'static str> {
        Err("runtime_binding_required")
    }
}

impl AnalysisProvenance {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn unresolved_is_explained(&self) -> Result<AnalysisProvenance, &'static str> {
        Err("runtime_binding_required")
    }
}

impl CodeGraphNode {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn type_is_consistent(&self) -> Result<CodeGraphNode, &'static str> {
        if ((self.type_status.clone()) == (String::from("resolved"))) && (self.type_name.is_none()) {
            return Err("resolved type status requires a type name");
        }
        if ((self.type_status.clone()) == (String::from("unknown"))) && (self.type_name.is_some()) {
            return Err("unknown type status cannot carry a type name");
        }
        Ok(self.clone())
    }
}

impl CodeGraphEdge {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn edge_fields_match_kind(&self) -> Result<CodeGraphEdge, &'static str> {
        let flow_fields: bool = (self.source_role.is_some()) || (self.target_role.is_some());
        Ok(self.clone())
    }
}

impl CodeGraphArtifact {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn closed_graph(&self) -> Result<CodeGraphArtifact, &'static str> {
        Err("runtime_binding_required")
    }
}

impl RuleSelector {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn sanitizer_context(&self) -> Result<RuleSelector, &'static str> {
        if ((self.role.clone()) == (String::from("sanitizer"))) && (self.security_context.is_none()) {
            return Err("sanitizer selector requires security_context");
        }
        if ((self.role.clone()) != (String::from("sanitizer"))) && (self.security_context.is_some()) {
            return Err("security_context is valid only for sanitizer selectors");
        }
        Ok(self.clone())
    }
}

impl CodeSecurityRuleSpec {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn complete_flow_rule(&self) -> Result<CodeSecurityRuleSpec, &'static str> {
        if (((self.languages.clone()).len() as i64)) != ((((self.languages.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) {
            return Err("rule languages must be unique");
        }
        if (((self.languages.clone()).len() as i64)) != (1_i64) {
            return Err("analysis rules must bind exactly one language frontend");
        }
        Ok(self.clone())
    }
}

impl PathEvidence {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn ordered_path(&self) -> Result<PathEvidence, &'static str> {
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AnalysisProvenance", "CodeGraphArtifact", "CodeGraphEdge", "CodeGraphNode", "CodeSecurityRuleSpec", "EvidenceConfidence", "GraphEdgeKind", "GraphNodeKind", "GRAPH_SCHEMA_VERSION", "PathEvidence", "PathEvidenceStep", "PATH_SCHEMA_VERSION", "PathStepRole", "RuleAnalysisKind", "RuleSelector", "SourceSpan"];
