#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryBreakGlassPager {
    pub initialized: bool,
}

impl InMemoryBreakGlassPager {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn notify_owners(&self, mut actor_oid: String, mut actor_display: String, mut reason_redacted: String, mut activated_at: String, mut expires_at: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    #[allow(clippy::type_complexity)]
    pub fn calls(&self) -> Vec<std::collections::BTreeMap<String, String>> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn next_error(&mut self, mut exc: String) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryBreakGlassPager"];
