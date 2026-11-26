#[derive(Clone, Debug, Default, PartialEq)]
pub struct UserContextRetentionReport {
    pub conversations: i64,
    pub memories: i64,
    pub briefing_runs: i64,
    pub queued_projection_deletes: i64,
    pub conversation_images: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProjectionDeleteJob {
    pub object_id: String,
    pub attempts: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresUserContextRetention {
    pub initialized: bool,
}

impl PostgresUserContextRetention {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn purge(&self, mut now: String, mut conversation_before: String, mut briefing_before: String, mut limit: i64) -> Result<UserContextRetentionReport, &'static str> {
        if !(((1_i64) <= (limit)) && ((limit) <= (5000_i64))) {
            return Err("limit MUST be in 1 5000");
        }
        let mut object_ids: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
        Ok(UserContextRetentionReport { queued_projection_deletes: ((object_ids.clone()).len() as i64), ..Default::default() })
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn claim_deletions(&self, mut now: String, mut limit: i64, mut lease_seconds: i64) -> Result<Vec<ProjectionDeleteJob>, &'static str> {
        if !(((1_i64) <= (limit)) && ((limit) <= (5000_i64))) {
            return Err("limit MUST be in 1 5000");
        }
        if !(((1_i64) <= (lease_seconds)) && ((lease_seconds) <= (3600_i64))) {
            return Err("lease_seconds MUST be in 1 3600");
        }
        Ok(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn complete_deletion(&self, mut object_id: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn retry_deletion(&self, mut object_id: String, mut available_at: String, mut error: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn conversation_rows(&self, mut connection: String, mut before: String, mut limit: i64) -> Vec<std::collections::BTreeMap<String, String>> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn connect(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn timeout(&self, mut connection: String) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresUserContextRetention", "ProjectionDeleteJob", "UserContextRetentionReport"];
