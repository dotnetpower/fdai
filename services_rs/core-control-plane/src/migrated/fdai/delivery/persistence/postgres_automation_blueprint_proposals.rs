#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresAutomationBlueprintProposalQueueConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ClaimedAutomationBlueprintProposal {
    pub key: String,
    pub claim_id: String,
    pub proposal: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresAutomationBlueprintProposalQueue {
    pub initialized: bool,
}

impl PostgresAutomationBlueprintProposalQueue {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn claim(&self, mut worker_id: String, mut lease_seconds: i64) -> Result<Option<ClaimedAutomationBlueprintProposal>, &'static str> {
        if !(((1_i64) <= (lease_seconds)) && ((lease_seconds) <= (300_i64))) {
            return Err("lease_seconds MUST be in 1 300");
        }
        Ok(Some(ClaimedAutomationBlueprintProposal { proposal: proposal_from_record(std::collections::BTreeMap::new()).unwrap_or_else(|_| String::new()), ..Default::default() }))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn mark_applied(&self, mut key: String, mut claim_id: String) -> bool {
        self.mark(key.clone(), claim_id.clone(), String::from("published"), None).await
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn mark_rejected(&self, mut key: String, mut claim_id: String, mut reason_code: String) -> bool {
        self.mark(key.clone(), claim_id.clone(), String::from("rejected"), Some(std::collections::BTreeMap::from([(String::from("rejection_reason"), reason_code.clone())]))).await
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn release(&self, mut key: String, mut claim_id: String) -> bool {
        self.mark(key.clone(), claim_id.clone(), String::from("pending"), Some(std::collections::BTreeMap::from([(String::from("claim_id"), String::new()), (String::from("claim_worker_id"), String::new()), (String::from("claim_expires_at"), String::new())]))).await
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn mark(&self, mut key: String, mut claim_id: String, mut status: String, mut extra: Option<std::collections::BTreeMap<String, String>>) -> bool {
        let update: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("dispatch_status"), status.clone())]);
        false
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

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn proposal_from_record(mut record: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    let payload: Option<String> = (record.clone()).get("payload").cloned();
    if !(true) {
        return Err("automation blueprint proposal record payload is malformed");
    }
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn required_str(mut record: std::collections::BTreeMap<String, String>, mut field: String) -> Result<String, &'static str> {
    let value: Option<String> = (record.clone()).get(field.as_str()).cloned();
    if (!(true)) || ((((value.clone()).unwrap_or_default()).trim().to_string()).is_empty()) {
        return Err("automation blueprint proposal field is malformed");
    }
    Ok((value.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn optional_str(mut value: String) -> Option<String> {
    if true { Some(value.clone()) } else { None }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ClaimedAutomationBlueprintProposal", "PostgresAutomationBlueprintProposalQueue", "PostgresAutomationBlueprintProposalQueueConfig"];
