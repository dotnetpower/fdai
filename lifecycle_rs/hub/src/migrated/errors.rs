#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HubStoreError {
    pub message: String,
}

impl HubStoreError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for HubStoreError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for HubStoreError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct UnknownInstallationError {
    pub message: String,
}

impl UnknownInstallationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for UnknownInstallationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for UnknownInstallationError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InstallationExistsError {
    pub message: String,
}

impl InstallationExistsError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for InstallationExistsError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for InstallationExistsError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct UnknownPlanError {
    pub message: String,
}

impl UnknownPlanError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for UnknownPlanError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for UnknownPlanError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReportConflictError {
    pub message: String,
}

impl ReportConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ReportConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ReportConflictError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReportAttemptGapError {
    pub message: String,
}

impl ReportAttemptGapError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ReportAttemptGapError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ReportAttemptGapError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReportProgressionError {
    pub message: String,
}

impl ReportProgressionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ReportProgressionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ReportProgressionError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PlanDigestMismatchError {
    pub message: String,
}

impl PlanDigestMismatchError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for PlanDigestMismatchError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PlanDigestMismatchError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StateRejectedError {
    pub message: String,
}

impl StateRejectedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for StateRejectedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for StateRejectedError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SchemaMismatchError {
    pub message: String,
}

impl SchemaMismatchError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for SchemaMismatchError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SchemaMismatchError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ConcurrentWriteError {
    pub message: String,
}

impl ConcurrentWriteError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ConcurrentWriteError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ConcurrentWriteError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SchemaMigrationPendingError {
    pub message: String,
}

impl SchemaMigrationPendingError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for SchemaMigrationPendingError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SchemaMigrationPendingError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EnrollmentProofError {
    pub message: String,
}

impl EnrollmentProofError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for EnrollmentProofError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for EnrollmentProofError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NotEnrolledError {
    pub message: String,
}

impl NotEnrolledError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for NotEnrolledError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for NotEnrolledError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NotPendingError {
    pub message: String,
}

impl NotPendingError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for NotPendingError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for NotPendingError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InstallationKeyMismatchError {
    pub message: String,
}

impl InstallationKeyMismatchError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for InstallationKeyMismatchError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for InstallationKeyMismatchError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct UnknownEntityError {
    pub message: String,
}

impl UnknownEntityError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for UnknownEntityError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for UnknownEntityError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EntityManagedError {
    pub message: String,
}

impl EntityManagedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for EntityManagedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for EntityManagedError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EntityNotReportedError {
    pub message: String,
}

impl EntityNotReportedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for EntityNotReportedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for EntityNotReportedError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EntitySettingsRejectedError {
    pub message: String,
}

impl EntitySettingsRejectedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for EntitySettingsRejectedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for EntitySettingsRejectedError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct OwnershipUnprovenError {
    pub message: String,
}

impl OwnershipUnprovenError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for OwnershipUnprovenError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for OwnershipUnprovenError {}

