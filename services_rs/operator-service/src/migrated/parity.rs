#[derive(Clone, Debug, Default, PartialEq)]
pub struct RouteParity {
    pub path: String,
    pub status: String,
    pub remaining_debt: Option<String>,
}

impl RouteParity {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.status.as_str(), "service-owned" | "blocked") { return Err("invalid status literal"); }
        Ok(())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["BLOCKED_ROUTE_PATHS", "PARITY_COMPLETE", "ROUTE_PARITY", "RouteParity"];
