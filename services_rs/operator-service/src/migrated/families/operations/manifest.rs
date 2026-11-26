#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperationRoute {
    pub path: String,
    pub method: String,
    pub name: String,
    pub operation: String,
    pub kind: String,
    pub roles: Vec<String>,
}

impl OperationRoute {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.method.as_str(), "GET" | "POST") { return Err("invalid method literal"); }
        if !matches!(self.kind.as_str(), "projection" | "proposal" | "stream" | "webhook") { return Err("invalid kind literal"); }
        Ok(())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["APPROVER_ROLES", "CONTRIBUTOR_ROLES", "OPERATIONS_ROUTE_MANIFEST", "READ_ROLES", "OperationRoute", "RouteKind"];
