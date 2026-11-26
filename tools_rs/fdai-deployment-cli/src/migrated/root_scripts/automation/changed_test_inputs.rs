#[derive(Clone, Debug, Default, PartialEq)]
pub struct InputIdentity {
    pub worktree: String,
    pub environment: String,
    pub stability: String,
}

impl InputIdentity {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn bound(&self) -> (String, String) {
        (self.worktree.clone(), self.environment.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn worktree_digests(mut root: String, mut excluded: Vec<String>) -> (String, String) {
    (String::new(), String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn environment_digest(mut root: String, mut environment: std::collections::BTreeMap<String, String>) -> String {
    let configured: String = (environment.clone()).get("UV_PROJECT_ENVIRONMENT").cloned().unwrap_or_else(|| String::from(""));
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn input_identity(mut environment: std::collections::BTreeMap<String, String>, mut excluded: Vec<String>) -> Option<InputIdentity> {
    Some(InputIdentity::default())
}

