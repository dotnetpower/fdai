#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConfigIssue {
    pub key: String,
    pub message: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ConfigError {
    pub message: String,
}

impl ConfigError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ConfigError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ConfigError {}

pub const PUBLIC_EXPORTS: &[&str] = &["ConfigError", "ConfigIssue"];
