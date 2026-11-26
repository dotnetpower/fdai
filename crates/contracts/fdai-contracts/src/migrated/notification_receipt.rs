pub const MAX_RECEIPT_BODY_BYTES: i64 = 4096;
pub const MAX_RECEIPT_ID_LENGTH: i64 = 256;
pub const DEFAULT_RECEIPT_SKEW_SECONDS: i64 = 300;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct NotificationDeliveryReceipt {
    pub audit_id: String,
    pub channel_id: String,
    pub publication_result: String,
    pub observed_at: String,
    pub provider_message_id: Option<String>,
}

pub const NOTIFICATION_DELIVERY_RECEIPT_TOPIC: &str = "fdai.notifications.delivery-receipts";
pub const NOTIFICATION_DELIVERY_RECEIPT_CONSUMER_GROUP: &str = "fdai-notification-delivery-receipts";
pub const NOTIFICATION_DELIVERY_RECEIPT_SCHEMA: &str = "notification-delivery-receipt";
pub const NOTIFICATION_DELIVERY_RECEIPT_SCHEMA_VERSION: &str = "1.0.0";
pub const RECEIPT_TIMESTAMP_HEADER: &str = "x-fdai-timestamp";
pub const RECEIPT_SIGNATURE_HEADER: &str = "x-fdai-signature";
pub const SIGNATURE_PREFIX: &str = "sha256=";
pub const SIGNATURE_DIGEST: &str = "^[0-9a-f]{64}$";
pub const PUBLICATION_RESULTS: &[&str] = &["published", "failed"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NotificationReceiptAuthenticationError {
    pub message: String,
}

impl NotificationReceiptAuthenticationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for NotificationReceiptAuthenticationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for NotificationReceiptAuthenticationError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NotificationReceiptFormatError {
    pub message: String,
}

impl NotificationReceiptFormatError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for NotificationReceiptFormatError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for NotificationReceiptFormatError {}

impl NotificationDeliveryReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn published(&self) -> bool {
        (self.publication_result.clone()) == (String::from("published"))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn idempotency_key(&self) -> String {
        notification_receipt_key(self.audit_id.clone(), self.channel_id.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn notification_receipt_key(mut audit_id: String, mut channel_id: String) -> String {
    if audit_id.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn compute_receipt_signature(mut secret: String, mut timestamp: String, mut body: Vec<u8>) -> Result<String, &'static str> {
    if (secret.clone()).is_empty() {
        return Err("notification receipt secret MUST be non-empty");
    }
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn verify_receipt_signature(mut secret: String, mut headers: std::collections::BTreeMap<String, String>, mut body: Vec<u8>, mut now: String, mut max_skew_seconds: i64) -> Result<String, &'static str> {
    if (max_skew_seconds) < (1_i64) {
        return Err("notification receipt max_skew_seconds MUST be positive");
    }
    let expected: String = compute_receipt_signature(secret.clone(), String::new(), body.clone()).unwrap_or_else(|_| String::new());
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn parse_receipt_body(mut body: Vec<u8>, mut observed_at: String) -> Result<NotificationDeliveryReceipt, &'static str> {
    if (((body.clone()).len() as i64)) > (MAX_RECEIPT_BODY_BYTES) {
        return Err("notification receipt body exceeds the configured limit");
    }
    Ok(NotificationDeliveryReceipt { audit_id: bounded_text(std::collections::BTreeMap::new(), String::from("audit_id")).unwrap_or_else(|_| String::new()), channel_id: bounded_text(std::collections::BTreeMap::new(), String::from("channel_id")).unwrap_or_else(|_| String::new()), publication_result: bounded_text(std::collections::BTreeMap::new(), String::from("publication_result")).unwrap_or_else(|_| String::new()), observed_at: observed_at.clone(), provider_message_id: optional_bounded_text(std::collections::BTreeMap::new(), String::from("provider_message_id")), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn encode_notification_delivery_receipt(mut receipt: NotificationDeliveryReceipt) -> std::collections::BTreeMap<String, String> {
    let mut payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from(NOTIFICATION_DELIVERY_RECEIPT_SCHEMA_VERSION)), (String::from("receipt_id"), String::new()), (String::from("audit_id"), receipt.audit_id.clone()), (String::from("channel_id"), receipt.channel_id.clone()), (String::from("publication_result"), receipt.publication_result.clone()), (String::from("observed_at"), String::new())]);
    if (receipt.provider_message_id.clone()).is_some() {
        payload.insert(String::from("provider_message_id"), (receipt.provider_message_id.clone()).unwrap_or_default());
    }
    payload.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn decode_notification_delivery_receipt(mut payload: std::collections::BTreeMap<String, String>) -> Result<NotificationDeliveryReceipt, &'static str> {
    if !(true) {
        return Err("notification receipt envelope MUST be an object");
    }
    let version: Option<String> = (payload.clone()).get("schema_version").cloned();
    if (version.clone()) != Some(String::from(NOTIFICATION_DELIVERY_RECEIPT_SCHEMA_VERSION)) {
        return Err("notification receipt envelope schema_version is unsupported");
    }
    let observed_raw: Option<String> = (payload.clone()).get("observed_at").cloned();
    if !(true) {
        return Err("notification receipt envelope observed_at MUST be a string");
    }
    let receipt: NotificationDeliveryReceipt = NotificationDeliveryReceipt { audit_id: bounded_text(payload.clone(), String::from("audit_id")).unwrap_or_else(|_| String::new()), channel_id: bounded_text(payload.clone(), String::from("channel_id")).unwrap_or_else(|_| String::new()), publication_result: bounded_text(payload.clone(), String::from("publication_result")).unwrap_or_else(|_| String::new()), provider_message_id: optional_bounded_text(payload.clone(), String::from("provider_message_id")), ..Default::default() };
    Ok(receipt.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bounded_text(mut value: std::collections::BTreeMap<String, String>, mut field: String) -> Result<String, &'static str> {
    let item: Option<String> = (value.clone()).get(field.as_str()).cloned();
    Ok((item.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn optional_bounded_text(mut value: std::collections::BTreeMap<String, String>, mut field: String) -> Option<String> {
    let item: Option<String> = (value.clone()).get(field.as_str()).cloned();
    let Some(mut item) = item.clone() else { return None; };
    Some(bounded_text(value.clone(), field.clone()).unwrap_or_else(|_| String::new()))
}

pub const PUBLIC_EXPORTS: &[&str] = &["DEFAULT_RECEIPT_SKEW_SECONDS", "MAX_RECEIPT_BODY_BYTES", "MAX_RECEIPT_ID_LENGTH", "NOTIFICATION_DELIVERY_RECEIPT_CONSUMER_GROUP", "NOTIFICATION_DELIVERY_RECEIPT_SCHEMA", "NOTIFICATION_DELIVERY_RECEIPT_SCHEMA_VERSION", "NOTIFICATION_DELIVERY_RECEIPT_TOPIC", "PUBLICATION_RESULTS", "RECEIPT_SIGNATURE_HEADER", "RECEIPT_TIMESTAMP_HEADER", "NotificationDeliveryReceipt", "NotificationReceiptAuthenticationError", "NotificationReceiptFormatError", "compute_receipt_signature", "decode_notification_delivery_receipt", "encode_notification_delivery_receipt", "notification_receipt_key", "parse_receipt_body", "verify_receipt_signature"];
