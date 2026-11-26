#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LitmusChaosInjector {
    pub initialized: bool,
}

impl LitmusChaosInjector {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn fault_type(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn inject(&self, mut target: String, mut params: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn stop(&self, mut target: String) {
        if !self.initialized {
            return;
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LitmusChaosResultProbe {
    pub initialized: bool,
}

impl LitmusChaosResultProbe {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observed(&self, mut signal: String, mut targets: Vec<String>) -> bool {
        self.initialized
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["LitmusChaosInjector", "LitmusChaosResultProbe"];
