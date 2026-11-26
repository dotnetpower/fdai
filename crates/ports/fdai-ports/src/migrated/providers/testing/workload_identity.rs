#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StaticWorkloadIdentity {
    pub initialized: bool,
}

impl StaticWorkloadIdentity {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get_token(&self, mut audience: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["StaticWorkloadIdentity"];
