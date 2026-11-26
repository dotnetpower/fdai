pub const SECOND: i64 = 1000000000;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RuntimeEventLagSource {
    pub initialized: bool,
}

impl RuntimeEventLagSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn wrap(&mut self, mut publisher: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn close(&mut self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn advance(&mut self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn key(mut event: String) -> Vec<u8> {
        if event.is_empty() {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn record(&mut self, mut event: String) {
        let tick: i64 = self.advance();
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn overflow(&mut self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observe(&self, mut now: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ObservedDecisionStagePublisher {
    pub initialized: bool,
}

impl ObservedDecisionStagePublisher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn emit(&self, mut event: String) {
        if !self.initialized {
            return;
        }
    }
}

