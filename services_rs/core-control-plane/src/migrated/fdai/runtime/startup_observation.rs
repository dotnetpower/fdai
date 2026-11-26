#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RuntimeStartupDurationSource {
    pub initialized: bool,
}

impl RuntimeStartupDurationSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn bind_readiness(&mut self, mut readiness: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_ready(&self) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observe(&self, mut now: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn close(&mut self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn record_first_ready(&mut self, mut observed_at: String) {
        if !self.initialized {
            return;
        }
    }
}

