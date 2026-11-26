use std::collections::BTreeMap;
pub const MAX_TRAVERSAL_DEPTH: i64 = 5;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReachedNode {
    pub resource_id: String,
    pub depth: i64,
    pub via_link_type: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TraversedEdge {
    pub source: String,
    pub target: String,
    pub link_type: String,
    pub depth: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BlastRadiusReport {
    pub target: String,
    pub traversal_depth: i64,
    pub traversal_links: Vec<String>,
    pub reached: Vec<ReachedNode>,
    pub edges: Vec<TraversedEdge>,
    pub truncated_at_depth: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BlastRadiusRequest {
    pub target: String,
    pub traversal_depth: i64,
    pub traversal_links: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InMemoryOntologyGraph {
    #[allow(clippy::type_complexity)]
    pub edges: BTreeMap<String, Vec<String>>,
    pub link_types: Vec<String>,
}

pub trait OntologyGraph {
    fn neighbors(&self, source: String, link_type: String) -> Vec<String>;
    fn has_link_type(&self, link_type: String) -> bool;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct UnknownLinkTypeError {
    pub message: String,
}

impl UnknownLinkTypeError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for UnknownLinkTypeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for UnknownLinkTypeError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TraversalDepthExceededError {
    pub message: String,
}

impl TraversalDepthExceededError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for TraversalDepthExceededError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for TraversalDepthExceededError {}

impl BlastRadiusReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn affected_count(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn as_json(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("target"), self.target.clone()), (String::from("traversal_depth"), String::new()), (String::from("traversal_links"), String::new()), (String::from("reached"), String::new()), (String::from("edges"), String::new()), (String::from("affected_count"), String::new()), (String::from("truncated_at_depth"), String::new())])
    }
}

impl InMemoryOntologyGraph {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn neighbors(&self, mut source: String, mut link_type: String) -> Vec<String> {
        if source.is_empty() {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn has_link_type(&self, mut link_type: String) -> bool {
        (self.link_types.clone()).contains(&(link_type.clone()))
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn simulate_blast_radius(mut graph: String, mut request: BlastRadiusRequest) -> Result<BlastRadiusReport, &'static str> {
    if (request.traversal_depth) < (1_i64) {
        return Err("traversal_depth MUST be at least 1");
    }
    if (request.traversal_depth) > (MAX_TRAVERSAL_DEPTH) {
        return Err("traversal_depthrequest.traversal_depth exceeds cap MAX_TRAVERSAL_DEPTH");
    }
    if (request.traversal_links.clone()).is_empty() {
        return Err("traversal_links MUST NOT be empty");
    }
    let mut seen: std::collections::BTreeMap<String, ReachedNode> = std::collections::BTreeMap::from([(request.target.clone(), ReachedNode { resource_id: request.target.clone(), depth: 0_i64, via_link_type: None, ..Default::default() })]);
    let mut edges: Vec<TraversedEdge> = Vec::<TraversedEdge>::new();
    let mut truncated: bool = false;
    Ok(BlastRadiusReport { target: request.target.clone(), traversal_depth: request.traversal_depth, traversal_links: request.traversal_links.clone(), edges: edges.clone(), truncated_at_depth: truncated, ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn check_truncation(mut graph: String, mut node: String, mut link_types: Vec<String>, mut seen: std::collections::BTreeMap<String, ReachedNode>) -> bool {
    if graph.is_empty() {
        return false;
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["MAX_TRAVERSAL_DEPTH", "BlastRadiusReport", "BlastRadiusRequest", "InMemoryOntologyGraph", "OntologyGraph", "ReachedNode", "TraversalDepthExceededError", "TraversedEdge", "UnknownLinkTypeError", "simulate_blast_radius"];
