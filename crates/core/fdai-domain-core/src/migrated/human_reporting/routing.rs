use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportLineRoutePlan {
    pub requester_ref: String,
    pub action_type: String,
    pub scope_ref: String,
    pub minimum_role: String,
    pub quorum: i64,
    pub graph_revision: String,
    pub path_revision: String,
    pub path_case_ids: Vec<String>,
    pub rungs: Vec<String>,
    pub planned_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportLineRoutingPolicy {
    pub action_types: Vec<String>,
    pub quorum_by_action: BTreeMap<String, i64>,
}

impl ReportLineRoutingPolicy {
    pub fn validate(&self) -> Result<(), &'static str> {
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportLineApprovalRouter {
    pub graphs: String,
    pub eligibility: String,
    pub policy: Box<ReportLineRoutingPolicy>,
    pub maximum_depth: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReportLineRouteUnavailableError {
    pub message: String,
}

impl ReportLineRouteUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ReportLineRouteUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ReportLineRouteUnavailableError {}

pub trait ReportingGraphReader {
    fn current_graph(&self, at: Option<String>) -> String;
}

pub trait ReportingLineEligibility {
    fn is_eligible(&self, subject_ref: String, minimum_role: String, action_type: String, scope_ref: String, at: String) -> String;
}

impl ReportLineRoutePlan {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        let material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("requester_ref"), self.requester_ref.clone()), (String::from("action_type"), self.action_type.clone()), (String::from("scope_ref"), self.scope_ref.clone()), (String::from("minimum_role"), self.minimum_role.clone()), (String::from("quorum"), String::new()), (String::from("path_revision"), self.path_revision.clone()), (String::from("path_case_ids"), String::new()), (String::from("rungs"), String::new())]);
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("requester_ref"), self.requester_ref.clone()), (String::from("action_type"), self.action_type.clone()), (String::from("scope_ref"), self.scope_ref.clone()), (String::from("minimum_role"), self.minimum_role.clone()), (String::from("quorum"), String::new()), (String::from("graph_revision"), self.graph_revision.clone()), (String::from("path_revision"), self.path_revision.clone()), (String::from("path_case_ids"), String::new()), (String::from("rungs"), String::new()), (String::from("planned_at"), String::new()), (String::from("route_digest"), String::new()), (String::from("approval_authority"), String::new())])
    }
}

impl ReportLineRoutingPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn selects(&self, mut action_type: String) -> bool {
        (self.action_types.clone()).contains(&(action_type.clone()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn quorum_for(&self, mut action_type: String) -> i64 {
        0_i64
    }
}

impl ReportLineApprovalRouter {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn plan(&self, mut requester_ref: String, mut action_type: String, mut scope_ref: String, mut minimum_role: String, mut at: String) -> Result<Option<ReportLineRoutePlan>, &'static str> {
        let mut rungs: Vec<String> = Vec::<String>::new();
        Ok(Some(ReportLineRoutePlan { action_type: action_type.clone(), scope_ref: scope_ref.clone(), minimum_role: minimum_role.clone(), path_revision: path_revision(Vec::new(), rungs.clone()), rungs: rungs.clone(), ..Default::default() }))
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn path_revision(mut path: Vec<String>, mut rungs: Vec<String>) -> String {
    let material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("edges"), String::new()), (String::from("rungs"), String::new())]);
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ReportLineApprovalRouter", "ReportLineRoutePlan", "ReportLineRouteUnavailableError", "ReportLineRoutingPolicy", "ReportingGraphReader", "ReportingLineEligibility"];
