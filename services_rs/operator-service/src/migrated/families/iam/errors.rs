#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct IamFamilyError {
    pub message: String,
}

impl IamFamilyError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for IamFamilyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for IamFamilyError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct IamPermissionError {
    pub message: String,
}

impl IamPermissionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for IamPermissionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for IamPermissionError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct IamConflictError {
    pub message: String,
}

impl IamConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for IamConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for IamConflictError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct IamExpiredError {
    pub message: String,
}

impl IamExpiredError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for IamExpiredError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for IamExpiredError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct IamNotFoundError {
    pub message: String,
}

impl IamNotFoundError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for IamNotFoundError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for IamNotFoundError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct IamUnavailableError {
    pub message: String,
}

impl IamUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for IamUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for IamUnavailableError {}

pub const PUBLIC_EXPORTS: &[&str] = &["IamConflictError", "IamExpiredError", "IamFamilyError", "IamNotFoundError", "IamPermissionError", "IamUnavailableError"];
