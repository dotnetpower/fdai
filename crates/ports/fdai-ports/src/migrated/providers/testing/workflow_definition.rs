#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryWorkflowDefinitionStore {
    pub initialized: bool,
}

impl InMemoryWorkflowDefinitionStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn put(&self, mut record: String) -> Result<String, &'static str> {
        Ok(record.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get(&self, mut definition_id: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list_visible(&self, mut principal_id: String, mut team_refs: Vec<String>) -> Vec<String> {
        let mut visible: Vec<String> = Vec::<String>::new();
        Vec::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryWorkflowBindingStore {
    pub initialized: bool,
}

impl InMemoryWorkflowBindingStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn create(&self, mut record: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list_for_principal(&self, mut principal_id: String) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn put(&self, mut record: String, mut expected_revision: i64) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn delete(&self, mut principal_id: String, mut binding_id: String) -> bool {
        self.initialized
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryWorkflowBindingStore", "InMemoryWorkflowDefinitionStore"];
