use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertScopeBinding {
    pub subscription_id: String,
    pub resource_group: String,
    pub tenant_ref: String,
    pub scope_ref: String,
    pub pseudonym_key: Vec<u8>,
    #[allow(clippy::type_complexity)]
    pub policy_bindings: BTreeMap<String, BTreeMap<String, String>>,
}

pub const GROUPS: &str = "Microsoft.Insights/actionGroups";
pub const PROCESSING: &str = "Microsoft.AlertsManagement/actionRules";
pub const HISTORY: &str = "Microsoft.AlertsManagement/alerts";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureAlertEvidenceSource {
    pub initialized: bool,
}

impl AzureAlertEvidenceSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn opaque(&self, mut kind: String, mut value: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn revision(&self, mut value: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn scope(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn collect(&self, mut now: String) -> String {
        self.collect_period(now.clone(), 86400_i64).await.unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn collect_period(&self, mut now: String, mut period_seconds: i64) -> Result<String, &'static str> {
        let mut raw: std::collections::BTreeMap<String, Vec<std::collections::BTreeMap<String, String>>> = std::collections::BTreeMap::<String, Vec<std::collections::BTreeMap<String, String>>>::new();
        let mut failures: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        let mut reasons: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("reverse_source_types_unverified"), String::from("ownership_unavailable"), String::from("incident_state_unavailable"), String::from("delivery_history_unavailable")]);
        let seed: String = self.revision(String::new());
        let evidence: String = self.normalize(raw.clone(), now.clone(), String::new(), String::new(), reasons.clone(), std::collections::BTreeSet::new(), seed.clone()).await.unwrap_or_else(|_| String::new());
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn stamp(&self, mut now: String, mut coverage: String, mut reasons: std::collections::BTreeSet<String>, mut seed: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    #[allow(clippy::too_many_arguments)]
    pub async fn normalize(&self, mut raw: std::collections::BTreeMap<String, Vec<std::collections::BTreeMap<String, String>>>, mut now: String, mut start: String, mut budget: String, mut reasons: std::collections::BTreeSet<String>, mut failed: std::collections::BTreeSet<String>, mut seed: String) -> Result<String, &'static str> {
        let mut rules: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        let mut targets: std::collections::BTreeMap<String, Vec<String>> = std::collections::BTreeMap::<String, Vec<String>>::new();
        let reverse: std::collections::BTreeMap<String, std::collections::BTreeSet<String>> = std::collections::BTreeMap::<String, std::collections::BTreeSet<String>>::new();
        let mut seen: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
        let mut groups: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        let mut available_groups: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        let mut audience_rows: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        let mut processing_rows: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn native(&self, mut raw: std::collections::BTreeMap<String, String>, mut collection: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn group(&self, mut raw: std::collections::BTreeMap<String, String>, mut native: String, mut budget: String, mut reasons: std::collections::BTreeSet<String>) -> Result<(String, Vec<String>), &'static str> {
        let mut members: Vec<String> = Vec::<String>::new();
        let mut automation: Vec<String> = Vec::<String>::new();
        let mut names: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
        Ok((String::new(), Vec::new()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn audience(&self, mut native: String, mut key: String, mut receiver: std::collections::BTreeMap<String, String>, mut binding: String, mut budget: String, mut reasons: std::collections::BTreeSet<String>, mut can_resolve: bool) -> Result<String, &'static str> {
        reasons.insert(String::from("audience_expansion_unavailable"));
        Ok(String::new())
    }
}

