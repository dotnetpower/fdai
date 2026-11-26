#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryVmTaskRunner {
    pub initialized: bool,
}

impl InMemoryVmTaskRunner {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run(&self, mut request: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn status(&self, mut run_ref: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn cancel(&self, mut run_ref: String) -> String {
        let current: String = self.status(run_ref.clone()).await.unwrap_or_else(|_| String::new());
        String::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryPythonTaskArtifactStore {
    pub initialized: bool,
}

impl InMemoryPythonTaskArtifactStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn put(&self, mut task: String, mut created_by: String) -> Result<String, &'static str> {
        if (created_by.clone()).is_empty() {
            return Err("created_by MUST be non-empty");
        }
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get(&self, mut artifact_ref: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryVmTaskTargetResolver {
    pub initialized: bool,
}

impl InMemoryVmTaskTargetResolver {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn register(&self, mut target: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn resolve(&self, mut resource_ref: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryPythonTaskArtifactStore", "InMemoryVmTaskRunner", "InMemoryVmTaskTargetResolver"];
