#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostGovernanceRoute {
    pub method: String,
    pub path: String,
    pub name: String,
    pub surface: String,
    pub legacy_alias: bool,
}

impl CostGovernanceRoute {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.method.as_str(), "GET" | "PUT") { return Err("invalid method literal"); }
        if !matches!(self.surface.as_str(), "availability" | "overview" | "resource-efficiency" | "optimization-cases" | "outcomes" | "settings") { return Err("invalid surface literal"); }
        Ok(())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["COST_GOVERNANCE_ROUTE_MANIFEST", "CostGovernanceRoute"];
