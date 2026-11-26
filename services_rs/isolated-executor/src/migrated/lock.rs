pub trait ExecutorShadowCommandHandler {
    fn handle(&self, command: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LockedIsolatedExecutorShadowService {
    pub initialized: bool,
}

impl LockedIsolatedExecutorShadowService {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn handle(&self, mut command: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ExecutorShadowCommandHandler", "LockedIsolatedExecutorShadowService"];
