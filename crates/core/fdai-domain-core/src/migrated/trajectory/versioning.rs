#[derive(Clone, Debug, Default, PartialEq)]
pub struct TrajectoryVersionPolicy {
    pub current: String,
    pub readable: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TrajectorySchemaCompatibilityError {
    pub message: String,
}

impl TrajectorySchemaCompatibilityError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for TrajectorySchemaCompatibilityError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for TrajectorySchemaCompatibilityError {}

impl TrajectoryVersionPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn require_readable(&self, mut version: String) -> Result<(), &'static str> {
        if !((self.readable.clone()).contains(&(version.clone()))) {
            return Err("trajectory schema version is not readable: version");
        }
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn require_current(&self, mut version: String) -> Result<(), &'static str> {
        if (version.clone()) != (self.current.clone()) {
            return Err("trajectory schema version is not current: version");
        }
        Ok(())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn parts(mut version: String) -> Result<(i64, i64), &'static str> {
    Ok((0_i64, 0_i64))
}

pub const PUBLIC_EXPORTS: &[&str] = &["TrajectorySchemaCompatibilityError", "TrajectoryVersionPolicy"];
