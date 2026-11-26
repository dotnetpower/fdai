#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresCostGovernanceConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresCostGovernanceStore {
    pub initialized: bool,
}

impl PostgresCostGovernanceStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read_cost_activation(&self, mut package_id: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn compare_and_set_cost_activation(&self, mut activation: String, mut expected_revision: i64) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn append_cost_analytics_snapshot(&self, mut snapshot_id: String, mut package_id: String, mut scope_id: String, mut observed_at: String, mut source_authority: String, mut complete: bool, mut payload: std::collections::BTreeMap<String, String>, mut evidence_digest: String, mut retention_until: String) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn append_cost_analytics_run_receipt(&self, mut receipt: String, mut scope_id: String) -> Result<bool, &'static str> {
        if (scope_id.clone()).is_empty() {
            return Err("Cost Analytics receipt scope MUST be non-empty");
        }
        Ok(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn cost_budget_data_available(&self) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn current_cost_analytics_snapshot_available(&self, mut scope_id: String, mut now: String, mut freshness: String) -> Result<bool, &'static str> {
        Ok(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn read_recent_complete_cost_observations(&self, mut package_id: String, mut ontology_release_digest: String, mut limit: i64) -> Result<Vec<String>, &'static str> {
        if !(((1_i64) <= (limit)) && ((limit) <= (1000_i64))) {
            return Err("cost observation hydration limit MUST be in 1 1000");
        }
        Ok(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read_cost_cursor(&self, mut package_id: String, mut scope_id: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn append_cost_page(&self, mut page: String, mut package_id: String, mut scope_id: String, mut expected_revision: i64, mut coverage_through_at: String, mut retention_floor_at: String) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn read_cost_observations(&self, mut package_id: String, mut scope_id: String, mut since: String, mut limit: i64) -> Result<Vec<String>, &'static str> {
        if !(((1_i64) <= (limit)) && ((limit) <= (1000_i64))) {
            return Err("cost observation read limit MUST be in 1 1000");
        }
        Ok(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn advance_cost_analysis_cursor(&self, mut package_id: String, mut scope_id: String, mut observation_id: String, mut observed_at: String, mut expected_analysis_revision: i64) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn connect(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn timeout(&self, mut conn: String) {
        if !self.initialized {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn activation(mut row: std::collections::BTreeMap<String, String>) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn cursor(mut row: std::collections::BTreeMap<String, String>) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn observation_values(mut item: String) -> Vec<String> {
    if item.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn current_observation_values(mut item: String) -> Vec<String> {
    if item.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn observation(mut row: std::collections::BTreeMap<String, String>) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresCostGovernanceConfig", "PostgresCostGovernanceStore"];
