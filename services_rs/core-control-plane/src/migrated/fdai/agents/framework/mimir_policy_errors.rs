#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PolicyRevisionRejectedError {
    pub message: String,
}

impl PolicyRevisionRejectedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for PolicyRevisionRejectedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PolicyRevisionRejectedError {}

pub const PUBLIC_EXPORTS: &[&str] = &["PolicyRevisionRejectedError"];
