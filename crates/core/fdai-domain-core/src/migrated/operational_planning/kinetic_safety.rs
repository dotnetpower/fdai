pub trait PreDispatchKineticSafetyWriter {
    fn persist(&self, action: String, correlation_id: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["PreDispatchKineticSafetyWriter"];
