#[derive(Clone, Debug, Default, PartialEq)]
pub struct BoundExecutorCommandContext {
    pub action_id: String,
    pub reservation_attempt: i64,
    pub source_revision: String,
    pub execution_path: String,
    pub safeguard_bundle_digest: String,
    pub reservation_identity_digest: String,
    pub evidence_identity_digest: String,
    pub target_digest: String,
    pub target_fence_generation: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ExecutorReceiptStorageUnavailableError {
    pub message: String,
}

impl ExecutorReceiptStorageUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ExecutorReceiptStorageUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ExecutorReceiptStorageUnavailableError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ExecutorReceiptRegistrationNotOwnedError {
    pub message: String,
}

impl ExecutorReceiptRegistrationNotOwnedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ExecutorReceiptRegistrationNotOwnedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ExecutorReceiptRegistrationNotOwnedError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ExecutorReceiptRegistrationUnobservedError {
    pub message: String,
}

impl ExecutorReceiptRegistrationUnobservedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ExecutorReceiptRegistrationUnobservedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ExecutorReceiptRegistrationUnobservedError {}

pub trait ExecutorReceiptJournal {
    fn register(&self, command: String, context: BoundExecutorCommandContext, registration_id: String) -> (String, bool);
    fn accept(&self, receipt: String, partition_key: String) -> bool;
    fn record_not_published(&self, command: String, registration_id: String);
    fn reconcile(&self) -> i64;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn receipt_matches_command(mut command: String, mut receipt: String, mut partition_key: String) -> bool {
    if command.is_empty() {
        return false;
    }
    false
}

