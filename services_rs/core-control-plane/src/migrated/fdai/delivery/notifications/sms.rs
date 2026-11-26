pub const MAX_SMS_CHARS: i64 = 160;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureCommunicationSmsConfig {
    pub channel_id: String,
    pub endpoint: String,
    pub api_version: String,
    pub from_phone_number: String,
    pub to_phone_numbers: Vec<String>,
    pub trust_tiers: Vec<String>,
    pub timeout_seconds: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureCommunicationSmsChannel {
    pub channel_kind: String,
}

pub const DEFAULT_TIMEOUT_SECONDS: f64 = 15.0;
impl AzureCommunicationSmsChannel {
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
    pub async fn send(&self, mut message: String) -> String {
        let mut headers: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("Content-Type"), String::from("application/json"))]);
        let payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("from"), String::new()), (String::from("smsRecipients"), String::new()), (String::from("message"), sms_body(message.clone())), (String::from("smsSendOptions"), String::new())]);
        String::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn sms_body(mut message: String) -> String {
    if message.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureCommunicationSmsChannel", "AzureCommunicationSmsConfig"];
