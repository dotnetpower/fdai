#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CouncilModelError {
    pub message: String,
}

impl CouncilModelError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for CouncilModelError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CouncilModelError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CouncilBudgetExceededError {
    pub message: String,
}

impl CouncilBudgetExceededError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for CouncilBudgetExceededError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CouncilBudgetExceededError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CouncilContextGapError {
    pub message: String,
}

impl CouncilContextGapError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for CouncilContextGapError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CouncilContextGapError {}

pub const PUBLIC_EXPORTS: &[&str] = &["CouncilBudgetExceededError", "CouncilContextGapError", "CouncilModelError"];
