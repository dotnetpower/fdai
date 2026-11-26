pub trait PipelinePrincipalRegistry {
    fn contains(&self, principal_id: String) -> bool;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryPipelinePrincipalRegistry {
    pub initialized: bool,
}

impl InMemoryPipelinePrincipalRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn contains(&self, mut principal_id: String) -> bool {
        self.initialized
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryPipelinePrincipalRegistry", "PipelinePrincipalRegistry"];
