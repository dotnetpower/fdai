pub const DEFAULT_TIMEOUT: f64 = 60.0;
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ChaosMeshInjector {
    pub initialized: bool,
}

impl ChaosMeshInjector {
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
pub struct ChaosMeshInjectedProbe {
    pub initialized: bool,
}

impl ChaosMeshInjectedProbe {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observed(&self, mut signal: String, mut targets: Vec<String>) -> bool {
        self.initialized
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn kubectl(mut args: Vec<String>, mut context: String, mut kubectl: String, mut stdin: Option<String>, mut timeout: f64) -> (i64, String, String) {
    (0_i64, String::new(), String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ChaosMeshInjectedProbe", "ChaosMeshInjector"];
