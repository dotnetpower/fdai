#[derive(Clone, Debug, Default, PartialEq)]
pub struct AksCommerceRoute {
    pub method: String,
    pub path: String,
    pub name: String,
}

impl AksCommerceRoute {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.method.as_str(), "GET") { return Err("invalid method literal"); }
        Ok(())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AKS_COMMERCE_ROUTE_MANIFEST", "AksCommerceRoute"];
