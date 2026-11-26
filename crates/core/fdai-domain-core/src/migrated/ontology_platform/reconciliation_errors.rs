#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReconciliationConflictError {
    pub message: String,
}

impl ReconciliationConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ReconciliationConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ReconciliationConflictError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReconciliationLedgerCorruptionError {
    pub message: String,
}

impl ReconciliationLedgerCorruptionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ReconciliationLedgerCorruptionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ReconciliationLedgerCorruptionError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReconciliationAttemptLimitError {
    pub message: String,
}

impl ReconciliationAttemptLimitError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ReconciliationAttemptLimitError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ReconciliationAttemptLimitError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReconciliationAggregateLimitError {
    pub message: String,
}

impl ReconciliationAggregateLimitError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ReconciliationAggregateLimitError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ReconciliationAggregateLimitError {}

