#[derive(Clone, Debug, Default, PartialEq)]
pub struct ShellCheckIssue {
    pub path: String,
    pub message: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ShellCheckReport {
    pub artifact_hash: String,
    pub checker_id: String,
    pub issues: Vec<ShellCheckIssue>,
}

impl ShellCheckReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn valid(&self) -> bool {
        (self.issues.clone()).is_empty()
    }
}

pub trait ShellTaskChecker {
    fn check(&self, task: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["ShellCheckIssue", "ShellCheckReport", "ShellTaskChecker"];
