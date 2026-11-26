pub const MAX_ACKNOWLEDGEMENT_BYTES: i64 = 4096;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DirectLineCredential {
    pub value: String,
    pub expires_at: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DirectLineConfig {
    pub channel_id: String,
    pub endpoint: String,
    pub conversation_id: String,
    pub trust_tiers: Vec<String>,
    pub sender_id: String,
    pub timeout_seconds: f64,
    pub credential_expiry_margin_seconds: f64,
    pub allow_insecure_loopback: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DirectLineNotificationChannel {
    pub channel_kind: String,
}

pub const ACTIVITY_DIGEST_PREFIX: &str = "activity-sha256:";
pub const DEFAULT_TIMEOUT_SECONDS: f64 = 10.0;
pub const API_SUFFIX: &str = "/v3/directline";
pub const CONVERSATION_ID: &str = "^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$";
pub const ACTIVITY_ID: &str = "^[\\x21-\\x7e]{1,256}$";
pub const CREDENTIAL: &str = "^[\\x21-\\x7e]{1,8192}$";
impl DirectLineNotificationChannel {
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
        let response: String = self.post_once(Vec::new(), std::collections::BTreeMap::from([(String::from("Authorization"), String::new()), (String::from("Content-Type"), String::new())])).await.unwrap_or_else(|_| String::new());
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn current_credential(&self) -> Result<DirectLineCredential, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn post_once(&self, mut payload: Vec<u8>, mut headers: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
        Err("Direct Line returned HTTP status the relay bot may already have the acti")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn utc_now() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn static_direct_line_credential(mut value: String) -> Result<String, &'static str> {
    let credential: DirectLineCredential = DirectLineCredential { value: value.clone(), ..Default::default() };
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn api_base(mut endpoint: String, mut allow_insecure_loopback: bool) -> Result<String, &'static str> {
    if endpoint.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_loopback_host(mut hostname: String) -> bool {
    if (hostname.to_lowercase()) == (String::from("localhost")) {
        return true;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn accepted_activity_id(mut response: String) -> Result<String, &'static str> {
    if response.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ACTIVITY_DIGEST_PREFIX", "DIRECT_LINE_TRUST_TIERS", "DirectLineConfig", "DirectLineCredential", "DirectLineCredentialProvider", "DirectLineNotificationChannel", "static_direct_line_credential"];
