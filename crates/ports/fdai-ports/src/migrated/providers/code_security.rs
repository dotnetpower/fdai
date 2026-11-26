pub trait CodeSecurityDriftProjector {
    fn call(&self, package: std::collections::BTreeMap<String, String>) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["CodeSecurityDriftProjector"];
