#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CachedHubArtifactStore {
    pub initialized: bool,
}

impl CachedHubArtifactStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn load(&self, mut kind: String, mut digest: String) -> Result<Option<String>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["CachedHubArtifactStore"];
