#[derive(Clone, Debug, Default, PartialEq)]
pub struct SemanticModelIdentityReadiness {
    pub identity: String,
    pub audiences: Vec<String>,
    pub timeout_seconds: f64,
    pub probe_id: String,
}

impl SemanticModelIdentityReadiness {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.identity.trim().is_empty() { return Err("identity must be non-empty"); }
        if self.probe_id.trim().is_empty() { return Err("probe_id must be non-empty"); }
        Ok(())
    }
}

pub const DEFAULT_TIMEOUT_SECONDS: f64 = 5.0;
impl SemanticModelIdentityReadiness {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn unavailable_reason(&self) -> Result<Option<String>, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run(&self, mut request: String) -> String {
        let reason: Option<String> = self.unavailable_reason().await.unwrap_or_else(|_| None);
        String::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["SemanticModelIdentityReadiness"];
