#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresEntitlementStateWriter {
    pub initialized: bool,
}

impl PostgresEntitlementStateWriter {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn publish(&self, mut notice: String, mut observed_at: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresEntitlementStateWriter"];
