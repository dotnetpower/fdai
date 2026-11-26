use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct StoredProposal {
    pub proposal_id: String,
    pub accepted_at: String,
    pub duplicate: bool,
    pub record: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionProposalClaim {
    pub key: String,
    pub claim_id: String,
    pub principal_id: String,
    pub payload: BTreeMap<String, String>,
    pub accepted_at: String,
    pub attempt: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WebhookProposalClaim {
    pub key: String,
    pub claim_id: String,
    pub payload: BTreeMap<String, String>,
    pub attempt: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HilDecisionProposalClaim {
    pub key: String,
    pub claim_id: String,
    pub payload: BTreeMap<String, String>,
    pub attempt: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportLineContactProposalClaim {
    pub key: String,
    pub claim_id: String,
    pub payload: BTreeMap<String, String>,
    pub attempt: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PoisonHaltClearProposalClaim {
    pub key: String,
    pub claim_id: String,
    pub payload: BTreeMap<String, String>,
    pub attempt: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadInvestigationProposalClaim {
    pub key: String,
    pub claim_id: String,
    pub request_id: String,
    pub principal_id: String,
    pub idempotency_key: String,
    pub correlation_id: Option<String>,
    pub payload: BTreeMap<String, String>,
    pub accepted_at: String,
    pub attempt: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IncidentInterventionProposalClaim {
    pub key: String,
    pub claim_id: String,
    pub request_id: String,
    pub principal_id: String,
    pub idempotency_key: String,
    pub correlation_id: String,
    pub payload: BTreeMap<String, String>,
    pub accepted_at: String,
    pub attempt: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StoredReplayEvent {
    pub sequence: i64,
    pub event: String,
    pub data: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StoredStateRecord {
    pub key: String,
    pub value: BTreeMap<String, String>,
    pub updated_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StoredStatePage {
    pub records: Vec<StoredStateRecord>,
    pub truncated: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresFamilyStoreUnavailableError {
    pub message: String,
}

impl PostgresFamilyStoreUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for PostgresFamilyStoreUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PostgresFamilyStoreUnavailableError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresProposalConflictError {
    pub message: String,
}

impl PostgresProposalConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for PostgresProposalConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PostgresProposalConflictError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresProcessNotVisibleError {
    pub message: String,
}

impl PostgresProcessNotVisibleError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for PostgresProcessNotVisibleError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PostgresProcessNotVisibleError {}

