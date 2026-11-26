#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StandingAuthorizationStoreError {
    pub message: String,
}

impl StandingAuthorizationStoreError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for StandingAuthorizationStoreError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for StandingAuthorizationStoreError {}

pub trait StandingAuthorizationLifecycleStore {
    fn apply(&self, command: String) -> String;
    fn read_revision(&self, revision_id: String) -> Option<String>;
    fn rebuild_snapshot(&self, family_id: String) -> Option<String>;
    fn check_fence(&self, fence: String) -> bool;
}

pub trait StandingAuthorizationLeaseStore {
    fn acquire(&self, request: String) -> String;
    fn check_commit_fence(&self, request: String) -> String;
    fn write_checkpoint(&self, checkpoint: String) -> bool;
    fn terminal_release(&self, record: String) -> bool;
    fn reconcile_provider_status(&self, lease_id: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["StandingAuthorizationLeaseStore", "StandingAuthorizationLifecycleStore", "StandingAuthorizationStoreError"];
