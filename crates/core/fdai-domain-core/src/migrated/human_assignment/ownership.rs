pub const PLATFORM_SCOPE: &str = "scope:platform";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AssignmentOwnershipError {
    pub message: String,
}

impl AssignmentOwnershipError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AssignmentOwnershipError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AssignmentOwnershipError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn render_assignment_ownership_yaml(mut base: String, mut intent: String) -> Result<String, &'static str> {
    let raw: std::collections::BTreeMap<String, String> = base_mapping(base.clone());
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn base_mapping(mut base: String) -> std::collections::BTreeMap<String, String> {
    let mut agents: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    std::collections::BTreeMap::from([(String::from("stewardship"), String::new())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["AssignmentOwnershipError", "render_assignment_ownership_yaml"];
