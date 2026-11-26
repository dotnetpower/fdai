#[derive(Clone, Debug, Default, PartialEq)]
pub struct TrialEntitlementResolver {
    pub catalog: String,
    pub store: String,
    pub installation_binding: String,
    pub deployment_binding: String,
    pub on_storage_error: Option<String>,
}

pub trait TrialStore {
    fn observe(&self, now: String) -> Option<String>;
}

impl TrialEntitlementResolver {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn resolve(&self, mut now: String) -> Result<String, &'static str> {
        if now.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn denied(mut reason: String, mut status: String) -> String {
    if reason.is_empty() {
        return String::new();
    }
    String::new()
}

