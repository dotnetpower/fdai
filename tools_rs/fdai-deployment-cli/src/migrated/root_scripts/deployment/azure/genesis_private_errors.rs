#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PrivateExecutionError {
    pub message: String,
}

impl PrivateExecutionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for PrivateExecutionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PrivateExecutionError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PrivateExecutionWaitError {
    pub message: String,
}

impl PrivateExecutionWaitError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for PrivateExecutionWaitError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PrivateExecutionWaitError {}

