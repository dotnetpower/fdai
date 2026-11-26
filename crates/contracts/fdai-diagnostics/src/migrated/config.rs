#[derive(Clone, Debug, Default, PartialEq)]
pub struct DevelopmentDiagnosticsConfig {
    pub service_id: String,
    pub execution_venue: String,
    pub socket_path: String,
    pub source_root: String,
    pub source_revision: String,
    pub service_input_digest: String,
    pub worktree_digest: String,
    pub runtime_scope_receipt_digest: String,
}

impl DevelopmentDiagnosticsConfig {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.execution_venue.as_str(), "local") { return Err("invalid execution_venue literal"); }
        Ok(())
    }
}

pub const SERVICE: &str = "^[a-z][a-z0-9-]{0,79}$";
pub const SHA40: &str = "^[0-9a-f]{40}$";
pub const SHA64: &str = "^[0-9a-f]{64}$";
pub const RECEIPT: &str = "^sha256:[0-9a-f]{64}$";
impl DevelopmentDiagnosticsConfig {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn from_environment(mut service_id: String, mut runtime_scope_receipt_digest: String, mut environment: Option<std::collections::BTreeMap<String, String>>) -> Result<Option<DevelopmentDiagnosticsConfig>, &'static str> {
        if service_id.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["DevelopmentDiagnosticsConfig"];
