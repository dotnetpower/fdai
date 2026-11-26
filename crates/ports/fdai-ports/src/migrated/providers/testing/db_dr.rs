pub const DEFAULT_ENDPOINT: &str = "fake-restore.example.internal";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FakeDbRestoreAdapter {
    pub initialized: bool,
}

impl FakeDbRestoreAdapter {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn restore(&mut self, mut config: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn teardown(&mut self, mut handle: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FakeIntegrityChecker {
    pub initialized: bool,
}

impl FakeIntegrityChecker {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn check(&mut self, mut handle: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FakeSmokeRunner {
    pub initialized: bool,
}

impl FakeSmokeRunner {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run(&mut self, mut handle: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn make_test_config(mut experiment_id: Option<String>, mut target_server_name: Option<String>, mut source_ref: Option<String>, mut target_resource_group: Option<String>, mut target_location: String) -> String {
    let default_source: String = String::from("/subscriptions/00000000-0000-0000-0000-000000000000/\" \"resourceGroups/rg-source/providers/Microsoft.DBforPostgreSQL/\" \"flexibleServers/src-server");
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["FakeDbRestoreAdapter", "FakeIntegrityChecker", "FakeSmokeRunner", "make_test_config"];
