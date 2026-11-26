use std::collections::BTreeMap;
pub const DEFAULT_MAX_BODY_BYTES: i64 = 256000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TeamsIngressConfig {
    pub tenant_id: String,
    pub allowed_service_urls: Vec<String>,
    pub principal_by_aad_object_id: BTreeMap<String, String>,
    pub max_body_bytes: i64,
    pub attachments_enabled: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AuthenticatedTeamsTurn {
    pub turn: String,
    pub service_url: String,
    pub principal_id: String,
    pub verification_ref: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TeamsIngressError {
    pub message: String,
}

impl TeamsIngressError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for TeamsIngressError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for TeamsIngressError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TeamsIngressVerifier {
    pub initialized: bool,
}

impl TeamsIngressVerifier {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn parse(&self, mut body: Vec<u8>, mut authorization: String, mut received_at: String) -> Result<AuthenticatedTeamsTurn, &'static str> {
        let payload: std::collections::BTreeMap<String, String> = json_object(body.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
        if (((payload.clone()).get("type").cloned()) != Some(String::from("message"))) || (((payload.clone()).get("channelId").cloned()) != Some(String::from("msteams"))) {
            return Err("Teams activity type or channel is unsupported codeunsupported_activity h");
        }
        let activity_service_url: String = normalize_teams_service_url(text(payload.clone(), String::from("serviceUrl"), 512_i64)).unwrap_or_else(|_| String::new());
        let token_service_url: String = normalize_teams_service_url(String::new()).unwrap_or_else(|_| String::new());
        let conversation: std::collections::BTreeMap<String, String> = object(payload.clone(), String::from("conversation")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let mut tenant_ids: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
        let conversation_tenant: Option<String> = (conversation.clone()).get("tenantId").cloned();
        if let Some(mut conversation_tenant) = conversation_tenant.clone() {
            tenant_ids.insert(bounded_text(conversation_tenant.clone(), String::from("tenantId"), 200_i64).unwrap_or_else(|_| String::new()));
        }
        let channel_data: Option<String> = (payload.clone()).get("channelData").cloned();
        let sender: std::collections::BTreeMap<String, String> = object(payload.clone(), String::from("from")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let aad_object_id: String = text(sender.clone(), String::from("aadObjectId"), 200_i64);
        let attachments: Vec<String> = attachments(String::new()).unwrap_or_else(|_| Vec::new());
        Ok(AuthenticatedTeamsTurn { service_url: activity_service_url.clone(), ..Default::default() })
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn normalize_teams_service_url(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
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
        return Err("Teams key is invalid codeinvalid_payload http_status400");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn text(mut value: std::collections::BTreeMap<String, String>, mut key: String, mut maximum: i64) -> String {
    bounded_text(String::new(), key.clone(), maximum).unwrap_or_else(|_| String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bounded_text(mut item: String, mut name: String, mut maximum: i64) -> Result<String, &'static str> {
    if (!(true)) || (((item.trim().to_string()).is_empty()) || ((((item.clone()).len() as i64)) > (maximum))) {
        return Err("Teams name is invalid codeinvalid_payload http_status400");
    }
    Ok(item.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn optional_text(mut value: std::collections::BTreeMap<String, String>, mut key: String, mut maximum: i64) -> Result<String, &'static str> {
    let item: String = (value.clone()).get(key.as_str()).cloned().unwrap_or_else(|| String::from(""));
    if (!(true)) || ((((item.clone()).len() as i64)) > (maximum)) {
        return Err("Teams key is invalid codeinvalid_payload http_status400");
    }
    Ok(item.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn attachments(mut raw: String) -> Result<Vec<String>, &'static str> {
    let mut attachments: Vec<String> = Vec::<String>::new();
    Ok(attachments.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["AuthenticatedTeamsTurn", "TeamsIngressConfig", "TeamsIngressError", "TeamsIngressVerifier", "normalize_teams_service_url"];
