#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct UnavailableAlertDirectApiExecutor {
    pub initialized: bool,
}

impl UnavailableAlertDirectApiExecutor {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn execute(&self, mut request: String) -> Result<String, &'static str> {
        Err("alert provider mutation adapter is not configured")
    }
}

pub trait DirectApiExecutionPort {
    fn execute(&self, action: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AlertUnavailableDirectApiExecutionPort {
    pub initialized: bool,
}

impl AlertUnavailableDirectApiExecutionPort {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn execute(&self, mut action: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AlertUnavailableDirectApiExecutionPort", "UnavailableAlertDirectApiExecutor"];
