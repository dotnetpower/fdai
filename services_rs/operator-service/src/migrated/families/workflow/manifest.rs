#[derive(Clone, Debug, Default, PartialEq)]
pub struct PaginationSpec {
    pub default_limit: i64,
    pub maximum_limit: i64,
    pub supports_offset: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowRouteSpec {
    pub method: String,
    pub path: String,
    pub name: String,
    pub operation: String,
    pub dispatch: String,
    pub required_roles: Vec<String>,
    pub maximum_body_bytes: i64,
    #[allow(clippy::type_complexity)]
    pub pagination: Option<Box<PaginationSpec>>,
}

impl WorkflowRouteSpec {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.method.as_str(), "GET" | "POST" | "PUT" | "DELETE") { return Err("invalid method literal"); }
        if !matches!(self.dispatch.as_str(), "read" | "proposal") { return Err("invalid dispatch literal"); }
        Ok(())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_skill_source_workflow_bridge(mut event_sink: Option<String>) -> String {
    if event_sink.is_none() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["APPROVER_ROLES", "CONTRIBUTOR_ROLES", "OWNER_ROLES", "PaginationSpec", "READER_ROLES", "WORKFLOW_FAMILY_ROUTE_MANIFEST", "WorkflowRouteSpec", "build_skill_source_workflow_bridge"];
