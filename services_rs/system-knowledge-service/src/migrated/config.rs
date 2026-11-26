use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TeamsTransport {
    #[default]
    BotFramework,
    OutgoingWebhook,
}

impl TeamsTransport {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::BotFramework => "bot_framework",
            Self::OutgoingWebhook => "outgoing_webhook",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TeamsSettings {
    pub application_id: String,
    pub bot_id: String,
    pub tenant_id: String,
    pub team_ids: Vec<String>,
    pub channel_ids: Vec<String>,
    pub allowed_service_urls: Vec<String>,
    pub principal_by_aad_object_id: BTreeMap<String, String>,
    pub jwks_url: String,
    pub client_secret: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TeamsOutgoingWebhookSettings {
    pub tenant_id: String,
    pub team_ids: Vec<String>,
    pub channel_ids: Vec<String>,
    pub principal_by_aad_object_id: BTreeMap<String, String>,
    pub hmac_secret: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SystemKnowledgeSettings {
    pub execution_venue: String,
    pub host: String,
    pub port: i64,
    pub catalog_path: String,
    pub expected_source_revision: Option<String>,
    pub ledger_path: String,
    pub claim_container_url: Option<String>,
    pub managed_identity_client_id: Option<String>,
    pub teams: Box<TeamsSettings>,
}

pub const HOST_ENV: &str = "FDAI_SYSTEM_KNOWLEDGE_HOST";
pub const PORT_ENV: &str = "FDAI_SYSTEM_KNOWLEDGE_PORT";
pub const CATALOG_PATH_ENV: &str = "FDAI_SYSTEM_KNOWLEDGE_CATALOG_PATH";
pub const SOURCE_REVISION_ENV: &str = "FDAI_SYSTEM_KNOWLEDGE_SOURCE_REVISION";
pub const LEDGER_PATH_ENV: &str = "FDAI_SYSTEM_KNOWLEDGE_LEDGER_PATH";
pub const CLAIM_CONTAINER_URL_ENV: &str = "FDAI_SYSTEM_KNOWLEDGE_CLAIM_CONTAINER_URL";
pub const APPLICATION_ID_ENV: &str = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_APPLICATION_ID";
pub const BOT_ID_ENV: &str = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_BOT_ID";
pub const TENANT_ID_ENV: &str = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TENANT_ID";
pub const TEAM_IDS_ENV: &str = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TEAM_IDS_JSON";
pub const CHANNEL_IDS_ENV: &str = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_CHANNEL_IDS_JSON";
pub const SERVICE_URLS_ENV: &str = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_SERVICE_URLS_JSON";
pub const PRINCIPAL_MAP_ENV: &str = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_PRINCIPAL_MAP_JSON";
pub const JWKS_URL_ENV: &str = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_JWKS_URL";
pub const CLIENT_SECRET_ENV: &str = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_CLIENT_SECRET";
pub const MANAGED_IDENTITY_CLIENT_ID_ENV: &str = "FDAI_SYSTEM_KNOWLEDGE_MI_CLIENT_ID";
pub const TEAMS_TRANSPORT_ENV: &str = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TRANSPORT";
pub const OUTGOING_HMAC_SECRET_ENV: &str = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_OUTGOING_HMAC_SECRET";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SystemKnowledgeConfigurationError {
    pub message: String,
}

impl SystemKnowledgeConfigurationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for SystemKnowledgeConfigurationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SystemKnowledgeConfigurationError {}

impl SystemKnowledgeSettings {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn teams_transport(&self) -> TeamsTransport {
        core::hint::black_box(Default::default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn parse(mut environ: std::collections::BTreeMap<String, String>) -> Result<SystemKnowledgeSettings, &'static str> {
        let values: std::collections::BTreeMap<String, String> = environ.clone();
        let host: String = ((values.clone()).get(HOST_ENV).cloned().unwrap_or_else(|| String::from("127.0.0.1"))).trim().to_string();
        if (host.clone()).is_empty() {
            return Err("HOST_ENV MUST be non-empty");
        }
        let port: i64 = port((values.clone()).get(PORT_ENV).cloned().unwrap_or_else(|| String::from("8015"))).unwrap_or_else(|_| 0_i64);
        let expected_revision: Option<String> = (Some(((values.clone()).get(SOURCE_REVISION_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None);
        let claim_container_url_raw: String = ((values.clone()).get(CLAIM_CONTAINER_URL_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
        let claim_container_url: Option<String> = if !(claim_container_url_raw.clone()).is_empty() { Some(https_url(claim_container_url_raw.clone(), String::from(CLAIM_CONTAINER_URL_ENV)).unwrap_or_else(|_| String::new())) } else { None };
        let transport: TeamsTransport = teams_transport(values.clone()).unwrap_or_else(|_| Default::default());
        let managed_identity_client_id: Option<String> = (Some(((values.clone()).get(MANAGED_IDENTITY_CLIENT_ID_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None);
        let tenant_id: String = bounded(required(values.clone(), String::from(TENANT_ID_ENV)).unwrap_or_else(|_| String::new()), String::from(TENANT_ID_ENV), 200_i64).unwrap_or_else(|_| String::new());
        let team_ids: std::collections::BTreeSet<String> = id_set(values.clone(), String::from(TEAM_IDS_ENV)).unwrap_or_else(|_| std::collections::BTreeSet::new());
        let channel_ids: std::collections::BTreeSet<String> = id_set(values.clone(), String::from(CHANNEL_IDS_ENV)).unwrap_or_else(|_| std::collections::BTreeSet::new());
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn normalize_service_url(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn teams_transport(mut values: std::collections::BTreeMap<String, String>) -> Result<TeamsTransport, &'static str> {
    if values.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn optional_hmac_secret(mut values: std::collections::BTreeMap<String, String>) -> Result<Option<String>, &'static str> {
    let value: Option<String> = (Some(((values.clone()).get(OUTGOING_HMAC_SECRET_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None);
    let Some(mut value) = value.clone() else { return Ok(None); };
    if (((value.clone()).len() as i64)) > (256_i64) {
        return Err("OUTGOING_HMAC_SECRET_ENV exceeds 256 characters");
    }
    Ok(Some(value.clone()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn port(mut raw: String) -> Result<i64, &'static str> {
    let value: i64 = (raw.clone()).trim().parse::<i64>().unwrap_or(0);
    if !(((1_i64) <= (value)) && ((value) <= (65535_i64))) {
        return Err("PORT_ENV MUST be in 1 65535");
    }
    Ok(value)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn required(mut values: std::collections::BTreeMap<String, String>, mut name: String) -> Result<String, &'static str> {
    let value: String = ((values.clone()).get(name.as_str()).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    if (value.clone()).is_empty() {
        return Err("name MUST be set");
    }
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bounded(mut value: String, mut name: String, mut maximum: i64) -> Result<String, &'static str> {
    if (((value.clone()).len() as i64)) > (maximum) {
        return Err("name exceeds maximum characters");
    }
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn json(mut values: std::collections::BTreeMap<String, String>, mut name: String) -> Result<String, &'static str> {
    if values.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn id_set(mut values: std::collections::BTreeMap<String, String>, mut name: String) -> Result<std::collections::BTreeSet<String>, &'static str> {
    let raw: String = json(values.clone(), name.clone()).unwrap_or_else(|_| String::new());
    Ok(std::collections::BTreeSet::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn principal_map(mut values: std::collections::BTreeMap<String, String>, mut name: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let raw: String = json(values.clone(), name.clone()).unwrap_or_else(|_| String::new());
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn service_urls(mut values: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeSet<String>, &'static str> {
    let raw: String = json(values.clone(), String::from(SERVICE_URLS_ENV)).unwrap_or_else(|_| String::new());
    if (!(false)) || (((raw.clone()).is_empty()) || ((((raw.clone()).len() as i64)) > (32_i64))) {
        return Err("SERVICE_URLS_ENV MUST be a non-empty bounded string array");
    }
    Ok(std::collections::BTreeSet::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn https_url(mut value: String, mut name: String) -> Result<String, &'static str> {
    Ok(value.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["SystemKnowledgeConfigurationError", "SystemKnowledgeSettings", "TeamsOutgoingWebhookSettings", "TeamsSettings", "TeamsTransport", "normalize_service_url"];
