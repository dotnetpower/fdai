use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum QueryKind {
    #[default]
    Find,
    Count,
}

impl QueryKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Find => "find",
            Self::Count => "count",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PredicateOp {
    #[default]
    Eq,
    Ne,
    Exists,
    Missing,
    In,
}

impl PredicateOp {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Eq => "eq",
            Self::Ne => "ne",
            Self::Exists => "exists",
            Self::Missing => "missing",
            Self::In => "in",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AbstainCode {
    #[default]
    UnrecognizedIntent,
    UnknownResourceType,
    EmptyInput,
    Ambiguous,
    SemanticModelUnavailable,
}

impl AbstainCode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::UnrecognizedIntent => "unrecognized_intent",
            Self::UnknownResourceType => "unknown_resource_type",
            Self::EmptyInput => "empty_input",
            Self::Ambiguous => "ambiguous",
            Self::SemanticModelUnavailable => "semantic_model_unavailable",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Predicate {
    pub field: String,
    pub op: PredicateOp,
    pub value: String,
}

impl Predicate {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.field.trim().is_empty() { return Err("field must be non-empty"); }
        if self.value.trim().is_empty() { return Err("value must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TypedQuery {
    pub resource_type: String,
    pub predicates: Vec<Predicate>,
    pub kind: QueryKind,
    #[allow(clippy::type_complexity)]
    pub projection: Option<Vec<String>>,
    pub limit: i64,
    pub evidence_refs: Vec<String>,
    pub compiler_revision: Option<String>,
    pub input_digest: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AbstainResult {
    pub code: AbstainCode,
    pub reason: String,
    pub hint: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct QueryRow {
    pub r#ref: String,
    pub properties: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct QueryResult {
    pub query: Box<TypedQuery>,
    pub rows: Vec<QueryRow>,
    pub count: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct QueryVerificationError {
    pub message: String,
}

impl QueryVerificationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for QueryVerificationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for QueryVerificationError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct QueryVerifier {
    pub initialized: bool,
}

impl QueryVerifier {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn known_resource_types(&self) -> std::collections::BTreeSet<String> {
        std::collections::BTreeSet::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn verify(&self, mut query: TypedQuery, mut expected_input_digest: Option<String>) -> Result<TypedQuery, &'static str> {
        Ok(query.clone())
    }
}

pub trait NlQueryCompiler {
    fn compile(&self, nl_text: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DeterministicPatternCompiler {
    pub initialized: bool,
}

impl DeterministicPatternCompiler {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn compile(&self, mut nl_text: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

impl QueryResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_empty(&self) -> bool {
        (self.count) == (0_i64)
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn predicate_matches(mut props: std::collections::BTreeMap<String, String>, mut predicate: Predicate) -> bool {
    if !((props.clone()).contains_key((predicate.field.clone()).as_str())) {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn execute_query(mut query: TypedQuery, mut projection: String, mut resources: Option<Vec<(String, std::collections::BTreeMap<String, String>)>>) -> Result<QueryResult, &'static str> {
    if resources.is_none() {
        if !(true) {
            return Err("execute_query requires an InMemoryProjection or an explicit  resources a");
        }
    }
    let mut matches: Vec<QueryRow> = Vec::<QueryRow>::new();
    let count: i64 = (matches.clone()).len() as i64;
    Ok(QueryResult { query: Box::new(query.clone()), count: count, ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["AbstainCode", "AbstainResult", "CompiledQuery", "DeterministicPatternCompiler", "NlQueryCompiler", "Predicate", "PredicateOp", "QueryKind", "QueryResult", "QueryRow", "QueryVerificationError", "QueryVerifier", "TypedQuery", "execute_query"];
