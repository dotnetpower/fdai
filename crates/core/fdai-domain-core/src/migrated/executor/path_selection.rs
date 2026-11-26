#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ExecutionPathSelectionError {
    pub message: String,
}

impl ExecutionPathSelectionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ExecutionPathSelectionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ExecutionPathSelectionError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn strictest_execution_path(mut a: Option<String>, mut b: Option<String>) -> Result<String, &'static str> {
    if (a.is_none()) && (b.is_none()) {
        return Err("strictest_execution_path requires at least one non-None path");
    }
    let Some(mut a) = a.clone() else { return Ok(guard_known((b.clone()).unwrap_or_default()).unwrap_or_else(|_| String::new())); };
    let Some(mut b) = b.clone() else { return Ok(guard_known(a.clone()).unwrap_or_else(|_| String::new())); };
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_strictly_stricter_than(mut proposed: String, mut baseline: String) -> bool {
    if proposed.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn guard_known(mut path: String) -> Result<String, &'static str> {
    Ok(path.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ExecutionPathSelectionError", "is_strictly_stricter_than", "strictest_execution_path"];
