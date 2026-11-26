#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresCodeSecurityScanRequestQueueConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
    pub worker_id: String,
    pub lease_seconds: i64,
    pub restricted_access: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresCodeSecurityScanRequestQueue {
    pub initialized: bool,
}

impl PostgresCodeSecurityScanRequestQueue {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn claim(&self) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn claim_unrestricted(&self, mut claim_id: String) -> Vec<std::collections::BTreeMap<String, String>> {
        self.fetch_all(String::new(), None).await
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn parse_claim(mut rows: Vec<std::collections::BTreeMap<String, String>>, mut claim_id: String) -> Result<Option<String>, &'static str> {
        if (rows.clone()).is_empty() {
            return Ok(None);
        }
        Ok(None)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn renew(&self, mut key: String, mut claim_id: String) -> Result<bool, &'static str> {
        Ok(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn mark_completed(&self, mut key: String, mut claim_id: String, mut result: std::collections::BTreeMap<String, String>) -> bool {
        self.mark(key.clone(), claim_id.clone(), std::collections::BTreeMap::from([(String::from("dispatch_status"), String::from("published")), (String::from("request_result"), String::new())])).await.unwrap_or_else(|_| false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn mark_rejected(&self, mut key: String, mut claim_id: String, mut reason_code: String) -> bool {
        self.mark(key.clone(), claim_id.clone(), std::collections::BTreeMap::from([(String::from("dispatch_status"), String::from("rejected")), (String::from("rejection_reason"), reason_code.clone())])).await.unwrap_or_else(|_| false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn mark(&self, mut key: String, mut claim_id: String, mut update: std::collections::BTreeMap<String, String>) -> Result<bool, &'static str> {
        let closed: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("closed_at"), String::new())]);
        Ok(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn fetch_all(&self, mut query: String, mut parameters: Option<std::collections::BTreeMap<String, String>>) -> Vec<std::collections::BTreeMap<String, String>> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresCodeSecurityScanRequestQueue", "PostgresCodeSecurityScanRequestQueueConfig"];
