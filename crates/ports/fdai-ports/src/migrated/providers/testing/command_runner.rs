#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RecordingCommandRunner {
    pub initialized: bool,
}

impl RecordingCommandRunner {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn execute(&self, mut plan: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["RecordingCommandRunner"];
