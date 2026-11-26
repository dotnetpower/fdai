#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryRunbookRegistry {
    pub initialized: bool,
}

impl InMemoryRunbookRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn register(&self, mut name: String, mut r#fn: String) -> Result<(), &'static str> {
        if (name.clone()).is_empty() {
            return Err("runbook name MUST be non-empty");
        }
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn names(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn execute(&self, mut name: String, mut params: std::collections::BTreeMap<String, String>, mut dry_run: bool) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    #[allow(clippy::type_complexity)]
    pub fn invocations(&self) -> Vec<(String, std::collections::BTreeMap<String, String>, bool)> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn next_error(&mut self, mut exc: String) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryRunbookRegistry", "RunbookCallable"];
