#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InvalidDocumentTransitionError {
    pub message: String,
}

impl InvalidDocumentTransitionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for InvalidDocumentTransitionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for InvalidDocumentTransitionError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn transition(mut current: String, mut target: String) -> Result<String, &'static str> {
    Ok(target.clone())
}

