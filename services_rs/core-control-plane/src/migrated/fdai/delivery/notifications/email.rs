pub const DEFAULT_MAX_POLL_ATTEMPTS: i64 = 60;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureCommunicationEmailConfig {
    pub channel_id: String,
    pub endpoint: String,
    pub api_version: String,
    pub sender_address: String,
    pub recipient_addresses: Vec<String>,
    pub trust_tiers: Vec<String>,
    pub timeout_seconds: f64,
    pub poll_interval_seconds: f64,
    pub max_poll_attempts: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureCommunicationEmailChannel {
    pub channel_kind: String,
}

pub const DEFAULT_TIMEOUT_SECONDS: f64 = 15.0;
pub const DEFAULT_POLL_INTERVAL_SECONDS: f64 = 1.0;
impl AzureCommunicationEmailChannel {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn channel_id(&self) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn trust_tiers(&self) -> std::collections::BTreeSet<String> {
        std::collections::BTreeSet::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn send(&self, mut message: String) -> Result<String, &'static str> {
        let mut headers: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("Content-Type"), String::from("application/json"))]);
        let payload: std::collections::BTreeMap<String, String> = acs_email_payload(message.clone(), Default::default());
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn wait_for_delivery(&self, mut operation_url: String, mut headers: std::collections::BTreeMap<String, String>, mut fallback_id: String) -> Result<String, &'static str> {
        Err("ACS Email operation did not complete within the configured poll budget")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn acs_email_payload(mut message: String, mut config: AzureCommunicationEmailConfig) -> std::collections::BTreeMap<String, String> {
    let provider_content: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("subject"), String::new()), (String::from("plainText"), String::new())]);
    std::collections::BTreeMap::from([(String::from("senderAddress"), config.sender_address.clone()), (String::from("content"), String::new()), (String::from("recipients"), String::new()), (String::from("headers"), String::new())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureCommunicationEmailChannel", "AzureCommunicationEmailConfig"];
