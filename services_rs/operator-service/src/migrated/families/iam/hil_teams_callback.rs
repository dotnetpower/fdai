#[allow(unused_imports)]
use fdai_contracts::http_compat::{json_kv, routing::{delete, get, head, options, patch, post, put}, Json, Path, Query, Router, StatusCode, Value};

pub const DEFAULT_TEAMS_MAX_BODY_BYTES: i64 = 32768;
pub const MAX_SERVICE_URLS: i64 = 32;
pub const MAX_TOKEN_LENGTH: i64 = 8192;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TeamsHilCallbackConfig {
    pub application_id: String,
    pub tenant_id: String,
    pub team_id: String,
    pub channel_id: String,
    pub allowed_service_urls: Vec<String>,
    pub max_body_bytes: i64,
}

impl TeamsHilCallbackConfig {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.application_id.trim().is_empty() { return Err("application_id must be non-empty"); }
        if self.tenant_id.trim().is_empty() { return Err("tenant_id must be non-empty"); }
        if self.team_id.trim().is_empty() { return Err("team_id must be non-empty"); }
        if self.channel_id.trim().is_empty() { return Err("channel_id must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct NormalizedTeamsActivity {
    pub activity_id: String,
    pub aad_object_id: String,
    pub audience: String,
    pub delegated_token: String,
    pub decision: String,
    pub justification: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub action_hash: String,
    pub service_url: String,
    pub verification_ref: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SharedServiceState {
    pub service_available: bool,
    pub policy_current: bool,
    pub caller_role: String,
    pub max_payload_bytes: usize,
}

pub async fn handle_post_hil_teams_activity_0() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "handler"), ("role_guard", "none"), ("byte_cap", "0")])))
}

#[must_use]
pub fn build_axum_router() -> Router {
    Router::new()
        .route("/hil/teams-activity", post(handle_post_hil_teams_activity_0))
}
pub const TEAMS_TENANT_ID_ENV: &str = "FDAI_TEAMS_TENANT_ID";
pub const TEAMS_SERVICE_URLS_ENV: &str = "FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON";
pub const HIL_DECISION_ACTION: &str = "fdai.hil.decision";
impl TeamsHilCallbackConfig {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn approval_audience(&self) -> String {
        format!("teams:{}:{}", self.team_id.clone(), self.channel_id.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn from_environment(mut values: std::collections::BTreeMap<String, String>, mut application_id: String, mut team_id: String, mut channel_id: String) -> Result<Option<TeamsHilCallbackConfig>, &'static str> {
        let tenant_id: String = ((values.clone()).get(TEAMS_TENANT_ID_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
        let raw_urls: String = ((values.clone()).get(TEAMS_SERVICE_URLS_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
        if !((!(application_id.clone()).is_empty()) && ((!(team_id.clone()).is_empty()) && (!(channel_id.clone()).is_empty()))) {
            return Ok(None);
        }
        if ((tenant_id.clone()).is_empty()) || ((raw_urls.clone()).is_empty()) {
            return Err("Teams A1 callback requires a tenant and allowed Bot service URLs");
        }
        Ok(None)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TeamsCallbackError {
    pub message: String,
}

impl TeamsCallbackError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for TeamsCallbackError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for TeamsCallbackError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TeamsHilCallbackNormalizer {
    pub initialized: bool,
}

impl TeamsHilCallbackNormalizer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn max_body_bytes(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn authenticate_transport(&self, mut authorization: Option<String>) -> Result<String, &'static str> {
        let mut authorization: String = match authorization.clone() { Some(_v) if !_v.is_empty() => _v, _ => return Err("Teams activity is missing its Bot service token status_code401 kindunaut") };
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn normalize(&self, mut body: Vec<u8>, mut authorization: Option<String>, mut approval_id: String, mut service_identity: Option<String>) -> Result<NormalizedTeamsActivity, &'static str> {
        let payload: std::collections::BTreeMap<String, String> = json_object(body.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
        if (((payload.clone()).get("type").cloned()) != Some(String::from("invoke"))) || (((payload.clone()).get("name").cloned()) != Some(String::from("adaptiveCard/action"))) {
            return Err("Teams approval activities MUST be adaptiveCardaction invokes status_code");
        }
        if ((payload.clone()).get("channelId").cloned()) != Some(String::from("msteams")) {
            return Err("Teams approval activities MUST originate on msteams status_code400 kindu");
        }
        let service_url: String = service_url(payload.clone(), String::new()).unwrap_or_else(|_| String::new());
        let channel_data: std::collections::BTreeMap<String, String> = object(payload.clone(), String::from("channelData")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let aad_object_id: String = text(object(payload.clone(), String::from("from")).unwrap_or_else(|_| std::collections::BTreeMap::new()), String::from("aadObjectId"), 200_i64).unwrap_or_else(|_| String::new());
        let value: std::collections::BTreeMap<String, String> = object(payload.clone(), String::from("value")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let action: std::collections::BTreeMap<String, String> = object(value.clone(), String::from("action")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        if ((action.clone()).get("verb").cloned()) != Some(String::from(HIL_DECISION_ACTION)) {
            return Err("Teams approval action verb is not the approval verb status_code400 kindu");
        }
        let delegated_token: String = text(object(value.clone(), String::from("authentication")).unwrap_or_else(|_| std::collections::BTreeMap::new()), String::from("token"), MAX_TOKEN_LENGTH).unwrap_or_else(|_| String::new());
        let data: std::collections::BTreeMap<String, String> = object(action.clone(), String::from("data")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        if (text(data.clone(), String::from("approval_id"), 128_i64).unwrap_or_else(|_| String::new())) != (approval_id.clone()) {
            return Err("Teams action data does not match the callback approval identity status_c");
        }
        Ok(NormalizedTeamsActivity { activity_id: text(payload.clone(), String::from("id"), 200_i64).unwrap_or_else(|_| String::new()), aad_object_id: aad_object_id.clone(), delegated_token: delegated_token.clone(), justification: optional_text(data.clone(), String::from("justification"), 1000_i64).unwrap_or_else(|_| String::new()), correlation_id: text(data.clone(), String::from("correlation_id"), 256_i64).unwrap_or_else(|_| String::new()), idempotency_key: text(data.clone(), String::from("idempotency_key"), 0_i64).unwrap_or_else(|_| String::new()), action_hash: text(data.clone(), String::from("action_hash"), 256_i64).unwrap_or_else(|_| String::new()), service_url: service_url.clone(), ..Default::default() })
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn make_hil_teams_callback_route(mut registry: Option<String>, mut outbox: Option<String>, mut authority: Option<String>, mut audit: Option<String>, mut context_reader: Option<String>, mut normalizer: Option<TeamsHilCallbackNormalizer>, mut clock: Option<String>) -> String {
    if registry.is_none() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn read_bounded_activity_body(mut request: String, mut maximum: i64) -> Result<Vec<u8>, &'static str> {
    if request.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn approval_id_from_activity(mut raw: Vec<u8>) -> Result<String, &'static str> {
    let data: std::collections::BTreeMap<String, String> = object(object(object(std::collections::BTreeMap::new(), String::from("value")).unwrap_or_else(|_| std::collections::BTreeMap::new()), String::from("action")).unwrap_or_else(|_| std::collections::BTreeMap::new()), String::from("data")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    Ok(text(data.clone(), String::from("approval_id"), 128_i64).unwrap_or_else(|_| String::new()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn activity_callback_id(mut approval_id: String, mut raw: Vec<u8>) -> String {
    if approval_id.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn service_url(mut payload: std::collections::BTreeMap<String, String>, mut token_service_url: String) -> Result<String, &'static str> {
    if payload.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn service_urls(mut raw: String) -> Result<Vec<String>, &'static str> {
    if raw.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn json_object(mut body: Vec<u8>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn unique_object(mut pairs: Vec<(String, String)>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn object(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let item: Option<String> = (value.clone()).get(key.as_str()).cloned();
    if !(true) {
        return Err("Teams activity key is invalid status_code400 kindbad_request");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn text(mut value: std::collections::BTreeMap<String, String>, mut key: String, mut maximum: i64) -> Result<String, &'static str> {
    let item: Option<String> = (value.clone()).get(key.as_str()).cloned();
    if (!(true)) || (((((item.clone()).unwrap_or_default()).trim().to_string()).is_empty()) || ((((((item.clone()).unwrap_or_default()).trim().to_string()).len() as i64)) > (maximum))) {
        return Err("Teams activity key MUST be bounded non-empty text status_code400 kindbad");
    }
    Ok(((item.clone()).unwrap_or_default()).trim().to_string())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn optional_text(mut value: std::collections::BTreeMap<String, String>, mut key: String, mut maximum: i64) -> Result<String, &'static str> {
    let item: Option<String> = (value.clone()).get(key.as_str()).cloned();
    if (!(true)) || ((((((item.clone()).unwrap_or_default()).trim().to_string()).len() as i64)) > (maximum)) {
        return Err("Teams activity key MUST be bounded text status_code400 kindbad_request");
    }
    Ok(((item.clone()).unwrap_or_default()).trim().to_string())
}

pub const PUBLIC_EXPORTS: &[&str] = &["DEFAULT_TEAMS_MAX_BODY_BYTES", "HIL_DECISION_ACTION", "NormalizedTeamsActivity", "TEAMS_ACTION_DATA_FIELDS", "TEAMS_SERVICE_URLS_ENV", "TEAMS_TENANT_ID_ENV", "TeamsCallbackError", "TeamsHilCallbackConfig", "TeamsHilCallbackNormalizer", "make_hil_teams_callback_route"];
