use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum LifecycleOwner {
    #[default]
    Odin,
    Thor,
    Forseti,
    Huginn,
    Heimdall,
    Var,
    Vidar,
    Bragi,
    Saga,
    Mimir,
    Norns,
    Muninn,
    Njord,
    Freyr,
    Loki,
}

impl LifecycleOwner {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Odin => "Odin",
            Self::Thor => "Thor",
            Self::Forseti => "Forseti",
            Self::Huginn => "Huginn",
            Self::Heimdall => "Heimdall",
            Self::Var => "Var",
            Self::Vidar => "Vidar",
            Self::Bragi => "Bragi",
            Self::Saga => "Saga",
            Self::Mimir => "Mimir",
            Self::Norns => "Norns",
            Self::Muninn => "Muninn",
            Self::Njord => "Njord",
            Self::Freyr => "Freyr",
            Self::Loki => "Loki",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum LinkSemanticTrait {
    #[default]
    Attachment,
    Authorization,
    Classification,
    Composition,
    Connectivity,
    Containment,
    Dependency,
    Evidence,
    Ownership,
    Reciprocal,
    Taxonomy,
    Traffic,
}

impl LinkSemanticTrait {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Attachment => "attachment",
            Self::Authorization => "authorization",
            Self::Classification => "classification",
            Self::Composition => "composition",
            Self::Connectivity => "connectivity",
            Self::Containment => "containment",
            Self::Dependency => "dependency",
            Self::Evidence => "evidence",
            Self::Ownership => "ownership",
            Self::Reciprocal => "reciprocal",
            Self::Taxonomy => "taxonomy",
            Self::Traffic => "traffic",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OntologyFunctionKind {
    #[default]
    QueryContract,
    Derive,
    Validate,
    Plan,
}

impl OntologyFunctionKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::QueryContract => "query",
            Self::Derive => "derive",
            Self::Validate => "validate",
            Self::Plan => "plan",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum LogicCapability {
    #[default]
    Predict,
    Optimize,
    Simulate,
}

impl LogicCapability {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Predict => "predict",
            Self::Optimize => "optimize",
            Self::Simulate => "simulate",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum LogicExecutionClass {
    #[default]
    Deterministic,
    SeededStochastic,
}

impl LogicExecutionClass {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Deterministic => "deterministic",
            Self::SeededStochastic => "seeded_stochastic",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PropertyDecl {
    pub r#type: String,
    pub required: bool,
    pub description: Option<String>,
    pub access_scope: String,
    pub purpose_binding: Vec<String>,
    pub query_terms: Vec<String>,
    #[allow(clippy::type_complexity)]
    pub value_query_terms: BTreeMap<String, Vec<String>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyProvenance {
    pub source_url: String,
    pub resolved_ref: String,
    pub content_hash: String,
    pub license: String,
    pub retrieved_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LifecycleCriterion {
    pub code: String,
    pub when: String,
    pub result: String,
    pub source_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LifecycleDeduplication {
    pub strategy: String,
    pub fields: Vec<String>,
    pub on_repeat: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObjectLifecycle {
    pub owner: LifecycleOwner,
    pub creation: Vec<LifecycleCriterion>,
    #[allow(clippy::type_complexity)]
    pub deduplication: Option<Box<LifecycleDeduplication>>,
    pub closure: Vec<LifecycleCriterion>,
    pub authority_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyObjectType {
    pub schema_version: String,
    pub name: String,
    pub version: String,
    pub key: String,
    pub properties: BTreeMap<String, PropertyDecl>,
    pub description: Option<String>,
    pub query_terms: Vec<String>,
    pub authority_class: String,
    pub freshness_max_age_seconds: Option<i64>,
    #[allow(clippy::type_complexity)]
    pub lifecycle: Option<Box<ObjectLifecycle>>,
    #[allow(clippy::type_complexity)]
    pub provenance: Option<Box<OntologyProvenance>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyLinkType {
    pub schema_version: String,
    pub name: String,
    pub version: String,
    pub from_type: String,
    pub to_type: String,
    pub cardinality: String,
    pub is_transitive: bool,
    pub is_causal: bool,
    pub temporal_order: bool,
    pub order_by_property: Option<String>,
    pub forward_role: Option<String>,
    pub reverse_role: Option<String>,
    pub semantic_traits: Vec<LinkSemanticTrait>,
    pub description: Option<String>,
    #[allow(clippy::type_complexity)]
    pub provenance: Option<Box<OntologyProvenance>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyInterfaceType {
    pub schema_version: String,
    pub name: String,
    pub version: String,
    pub properties: BTreeMap<String, PropertyDecl>,
    pub required_links: Vec<String>,
    pub supported_actions: Vec<String>,
    pub extends: Vec<String>,
    pub description: Option<String>,
    #[allow(clippy::type_complexity)]
    pub provenance: Option<Box<OntologyProvenance>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyInterfaceImplementation {
    pub object_type: String,
    pub interfaces: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyFunctionType {
    pub schema_version: String,
    pub name: String,
    pub version: String,
    pub kind: OntologyFunctionKind,
    pub capabilities: Vec<LogicCapability>,
    pub artifact_digest: String,
    pub publisher: String,
    pub input_schema: BTreeMap<String, String>,
    pub output_schema: BTreeMap<String, String>,
    pub read_sets: Vec<String>,
    pub execution_class: LogicExecutionClass,
    pub seed_field: Option<String>,
    pub required_role: String,
    pub purpose_bindings: Vec<String>,
    pub allowed_agents: Vec<String>,
    pub timeout_seconds: i64,
    pub cpu_millis: i64,
    pub memory_bytes: i64,
    pub max_output_bytes: i64,
    pub network_allowed: bool,
    pub credentials_allowed: bool,
    pub execution_authority: bool,
    pub learned_through: Option<String>,
    pub evidence_grade: Option<String>,
    pub promotion_gate: Option<String>,
    #[allow(clippy::type_complexity)]
    pub provenance: Option<Box<OntologyProvenance>>,
}

impl OntologyFunctionType {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

impl OntologyLinkType {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn semantic_roles(&self) -> Result<OntologyLinkType, &'static str> {
        if (self.forward_role.is_none()) != (self.reverse_role.is_none()) {
            return Err("ontology link roles MUST be declared together");
        }
        Ok(self.clone())
    }
}

impl OntologyFunctionType {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn function_contract(&self) -> Result<OntologyFunctionType, &'static str> {
        if (self.credentials_allowed) && (!(self.network_allowed)) {
            return Err("credentialed ontology function requires network access");
        }
        Ok(self.clone())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["LifecycleCriterion", "LifecycleDeduplication", "LifecycleOwner", "ObjectLifecycle", "OntologyFunctionKind", "OntologyFunctionType", "OntologyInterfaceType", "OntologyInterfaceImplementation", "OntologyLinkType", "OntologyObjectType", "OntologyProvenance", "PromotionGate", "LogicCapability", "LogicExecutionClass", "PropertyDecl"];
