#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PlanningVmTaskRunner {
    pub initialized: bool,
}

impl PlanningVmTaskRunner {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run(&self, mut request: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn status(&self, mut run_ref: String) -> Result<String, &'static str> {
        Err("planning runner has no live status for run_refr")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn cancel(&self, mut run_ref: String) -> Result<String, &'static str> {
        Err("planning runner cannot cancel run_refr")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PlanningVmTaskRunner"];
