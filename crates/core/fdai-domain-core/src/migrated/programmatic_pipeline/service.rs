#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProgrammaticPipelineService {
    pub initialized: bool,
}

impl ProgrammaticPipelineService {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run(&self, mut request: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn cancel(&self, mut run_id: String) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn rejected(&self, mut request: String, mut detail: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ProgrammaticPipelineService"];
