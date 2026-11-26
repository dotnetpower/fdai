#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryToolProvider {
    pub initialized: bool,
}

impl InMemoryToolProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn prime(&self, mut tool_id: String, mut arguments: std::collections::BTreeMap<String, String>, mut response: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn call(&self, mut artifact: String, mut arguments: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NoOpToolProvider {
    pub initialized: bool,
}

impl NoOpToolProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn call(&self, mut artifact: String, mut arguments: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
        Err("NoOpToolProvider refuses tool call to artifact.idr: self._reason")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn key(mut arguments: std::collections::BTreeMap<String, String>) -> Vec<(String, String)> {
    if arguments.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryToolProvider", "NoOpToolProvider"];
