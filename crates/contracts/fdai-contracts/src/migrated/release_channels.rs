pub const RELEASE_CHANNELS: &[&str] = &["DEV", "RELEASE_CANDIDATE", "RELEASE"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReleaseChannelError {
    pub message: String,
}

impl ReleaseChannelError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ReleaseChannelError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ReleaseChannelError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn current_release_channel(mut value: String) -> Result<String, &'static str> {
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn verified_release_channel(mut value: String) -> String {
    current_release_channel(String::new()).unwrap_or_else(|_| String::new())
}

