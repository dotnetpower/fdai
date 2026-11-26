#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SecretNotFoundError {
    pub message: String,
}

impl SecretNotFoundError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for SecretNotFoundError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SecretNotFoundError {}

pub trait SecretProvider {
    fn get(&self, name: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["SecretNotFoundError", "SecretProvider"];
