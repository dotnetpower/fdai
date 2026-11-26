#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NoOpBlastProbe {
    pub initialized: bool,
}

impl NoOpBlastProbe {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn measure(&mut self, mut query: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn force_verdict(&mut self, mut verdict: String, mut reason: String, mut metrics: Option<std::collections::BTreeMap<String, f64>>, mut degraded: bool) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn next_timeout(&mut self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn next_error(&mut self, mut exc: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn queries(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["NoOpBlastProbe"];
