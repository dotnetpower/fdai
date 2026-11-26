#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GitOpsAlertIaCSourceReader {
    pub initialized: bool,
}

impl GitOpsAlertIaCSourceReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read(&self, mut path: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ScopedAlertAuthority {
    pub initialized: bool,
}

impl ScopedAlertAuthority {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn approvals(&self, mut plan: String) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn dispatch_evidence(&self, mut plan: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn allows_development_single_owner_quorum(&self, mut plan: String) -> bool {
        self.initialized
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ScopedAlertRecoveryAuthority {
    pub initialized: bool,
}

impl ScopedAlertRecoveryAuthority {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn admission(&self, mut action: String, mut plan: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ScopedAlertAuthorityFence {
    pub initialized: bool,
}

impl ScopedAlertAuthorityFence {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn hold(&self, mut action: String, mut plan: String, mut pr: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct UnavailableAlertAuthorityFence {
    pub initialized: bool,
}

impl UnavailableAlertAuthorityFence {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn hold(&self, mut action: String, mut plan: String, mut pr: String) -> Result<Vec<String>, &'static str> {
        Err("alert_provider_conditional_update_or_exclusive_writer_missing")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn postgres_lock_binding(mut resource_lock: Option<String>) -> Option<(String, String)> {
    if resource_lock.is_none() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn build_alert_pr_execution_port(mut fallback: String, mut audit_store: String, mut publisher: String, mut resource_lock: Option<String>, mut coordinator: Option<String>, mut promotion_registry: String, mut ontology_release: String, mut decision_evidence_provider: Option<String>, mut process_store: Option<String>, mut environment: Option<std::collections::BTreeMap<String, String>>, mut policy: Option<String>, mut clock: String) -> String {
    let mut authorities: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    let recoveries: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    let mut fences: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn build_alert_plan_artifacts(mut store: String, mut publisher: String, mut environment: Option<std::collections::BTreeMap<String, String>>) -> Option<String> {
    if store.is_empty() {
        return None;
    }
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["GitOpsAlertIaCSourceReader", "build_alert_pr_execution_port"];
