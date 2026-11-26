#[derive(Clone, Debug, Default, PartialEq)]
pub struct ShadowSinkAppendResult {
    pub receipt: String,
    pub persistence: String,
}

pub const STATE_PREFIX: &str = "read-investigation-shadow:";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ShadowReceiptIdentityConflictError {
    pub message: String,
}

impl ShadowReceiptIdentityConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ShadowReceiptIdentityConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ShadowReceiptIdentityConflictError {}

pub trait ShadowComparisonSink {
    fn append(&self, receipt: String) -> ShadowSinkAppendResult;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryShadowComparisonSink {
    pub initialized: bool,
}

impl InMemoryShadowComparisonSink {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn append(&self, mut receipt: String) -> Result<ShadowSinkAppendResult, &'static str> {
        Ok(ShadowSinkAppendResult { receipt: receipt.clone(), ..Default::default() })
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list_receipts(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StateStoreShadowComparisonSink {
    pub initialized: bool,
}

impl StateStoreShadowComparisonSink {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn append(&self, mut receipt: String) -> Result<ShadowSinkAppendResult, &'static str> {
        let value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("record_type"), String::from("read_investigation.resource_state_shadow.v1")), (String::from("receipt"), String::new())]);
        Ok(ShadowSinkAppendResult::default())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryShadowComparisonSink", "StateStoreShadowComparisonSink", "ShadowComparisonSink", "ShadowReceiptIdentityConflictError", "ShadowSinkAppendResult"];
