#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AssignmentServiceError {
    pub message: String,
}

impl AssignmentServiceError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AssignmentServiceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AssignmentServiceError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AssignmentConflictError {
    pub message: String,
}

impl AssignmentConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AssignmentConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AssignmentConflictError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AssignmentPermissionError {
    pub message: String,
}

impl AssignmentPermissionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AssignmentPermissionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AssignmentPermissionError {}

pub const PUBLIC_EXPORTS: &[&str] = &["AssignmentConflictError", "AssignmentPermissionError", "AssignmentServiceError"];
