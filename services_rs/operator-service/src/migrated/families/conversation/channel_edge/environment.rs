use std::collections::BTreeMap;
pub const DEFAULT_PORT: i64 = 8014;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PrincipalScopeSettings {
    pub scope_ref: String,
    pub roles: Vec<String>,
    pub locale: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SlackEdgeSettings {
    pub signing_secret: String,
    pub bot_token: String,
    pub team_id: String,
    pub principal_by_sender_id: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TeamsEdgeSettings {
    pub application_id: String,
    pub tenant_id: String,
    pub principal_by_aad_object_id: BTreeMap<String, String>,
    pub allowed_service_urls: Vec<String>,
    pub jwks_url: String,
    pub client_secret: Option<String>,
    pub managed_identity_client_id: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AttachmentEdgeSettings {
    pub intake_origin: String,
    pub intake_audience: String,
    pub client_id: String,
    pub tenant_id: Option<String>,
    pub client_secret: Option<String>,
    pub scratch_directory: String,
    pub max_content_bytes: i64,
    pub principal_manifest_digest: String,
    pub slack_files_info_url: Option<String>,
    pub slack_metadata_hosts: Vec<String>,
    pub slack_download_hosts: Vec<String>,
    pub teams_url_template: Option<String>,
    pub teams_audience: Option<String>,
    pub teams_hosts: Vec<String>,
    pub teams_audiences: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelEdgeEnvironment {
    pub values: BTreeMap<String, String>,
    pub host: String,
    pub port: i64,
    pub execution_venue: String,
    pub enabled_channels: Vec<String>,
    pub database_url: String,
    pub database_role: String,
    pub kafka_bootstrap_servers: String,
    pub semantic_request_topic: String,
    pub semantic_projection_topic: String,
    pub semantic_physical_topic: Option<String>,
    pub semantic_authentication_receipt_ref_enabled: bool,
    pub semantic_consumer_group: String,
    pub semantic_client_id: String,
    pub managed_identity_client_id: Option<String>,
    pub attachments_enabled: bool,
    #[allow(clippy::type_complexity)]
    pub attachments: Option<Box<AttachmentEdgeSettings>>,
    pub principal_scopes: BTreeMap<String, PrincipalScopeSettings>,
    #[allow(clippy::type_complexity)]
    pub slack: Option<Box<SlackEdgeSettings>>,
    #[allow(clippy::type_complexity)]
    pub teams: Option<Box<TeamsEdgeSettings>>,
}

pub const HOST_ENV: &str = "FDAI_CHANNEL_EDGE_HOST";
pub const PORT_ENV: &str = "FDAI_CHANNEL_EDGE_PORT";
pub const ENABLED_CHANNELS_ENV: &str = "FDAI_CHANNEL_EDGE_ENABLED_CHANNELS";
pub const DATABASE_URL_ENV: &str = "FDAI_DATABASE_URL";
pub const DATABASE_ROLE_ENV: &str = "FDAI_DATABASE_ROLE";
pub const KAFKA_BOOTSTRAP_ENV: &str = "FDAI_KAFKA_BOOTSTRAP_SERVERS";
pub const SEMANTIC_REQUEST_TOPIC_ENV: &str = "FDAI_SEMANTIC_TURN_REQUEST_TOPIC";
pub const SEMANTIC_PROJECTION_TOPIC_ENV: &str = "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC";
pub const SEMANTIC_PHYSICAL_TOPIC_ENV: &str = "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC";
pub const SEMANTIC_AUTHENTICATION_RECEIPT_REF_ENV: &str = "FDAI_SEMANTIC_AUTHENTICATION_RECEIPT_REF_ENABLED";
pub const SEMANTIC_CONSUMER_GROUP_ENV: &str = "FDAI_CHANNEL_EDGE_SEMANTIC_CONSUMER_GROUP_ID";
pub const SEMANTIC_CLIENT_ID_ENV: &str = "FDAI_CHANNEL_EDGE_SEMANTIC_CLIENT_ID";
pub const PRINCIPAL_SCOPES_ENV: &str = "FDAI_CHANNEL_EDGE_PRINCIPAL_SCOPES_JSON";
pub const ATTACHMENTS_ENABLED_ENV: &str = "FDAI_CHANNEL_ATTACHMENTS_ENABLED";
pub const ATTACHMENT_INTAKE_ORIGIN_ENV: &str = "FDAI_CHANNEL_ATTACHMENT_INTAKE_ORIGIN";
pub const ATTACHMENT_INTAKE_AUDIENCE_ENV: &str = "FDAI_CHANNEL_ATTACHMENT_INTAKE_AUDIENCE";
pub const ATTACHMENT_CLIENT_ID_ENV: &str = "FDAI_CHANNEL_ATTACHMENT_CLIENT_ID";
pub const ATTACHMENT_TENANT_ID_ENV: &str = "FDAI_CHANNEL_ATTACHMENT_TENANT_ID";
pub const ATTACHMENT_CLIENT_SECRET_ENV: &str = "FDAI_CHANNEL_ATTACHMENT_CLIENT_SECRET";
pub const ATTACHMENT_SCRATCH_DIR_ENV: &str = "FDAI_CHANNEL_ATTACHMENT_SCRATCH_DIR";
pub const ATTACHMENT_SCRATCH_ENCRYPTED_ENV: &str = "FDAI_CHANNEL_ATTACHMENT_SCRATCH_ENCRYPTED";
pub const ATTACHMENT_MAX_BYTES_ENV: &str = "FDAI_CHANNEL_ATTACHMENT_MAX_CONTENT_BYTES";
pub const SLACK_FILES_INFO_URL_ENV: &str = "FDAI_SLACK_FILES_INFO_URL";
pub const SLACK_ATTACHMENT_METADATA_HOSTS_ENV: &str = "FDAI_SLACK_ATTACHMENT_METADATA_HOSTS_JSON";
pub const SLACK_ATTACHMENT_DOWNLOAD_HOSTS_ENV: &str = "FDAI_SLACK_ATTACHMENT_DOWNLOAD_HOSTS_JSON";
pub const TEAMS_ATTACHMENT_URL_TEMPLATE_ENV: &str = "FDAI_TEAMS_ATTACHMENT_URL_TEMPLATE";
pub const TEAMS_ATTACHMENT_AUDIENCE_ENV: &str = "FDAI_TEAMS_ATTACHMENT_AUDIENCE";
pub const TEAMS_ATTACHMENT_HOSTS_ENV: &str = "FDAI_TEAMS_ATTACHMENT_HOSTS_JSON";
pub const TEAMS_ATTACHMENT_AUDIENCES_ENV: &str = "FDAI_TEAMS_ATTACHMENT_AUDIENCES_JSON";
pub const SLACK_SIGNING_SECRET_ENV: &str = "FDAI_SLACK_SIGNING_SECRET";
pub const SLACK_BOT_TOKEN_ENV: &str = "FDAI_SLACK_BOT_TOKEN";
pub const SLACK_TEAM_ID_ENV: &str = "FDAI_SLACK_TEAM_ID";
pub const SLACK_PRINCIPAL_MAP_ENV: &str = "FDAI_SLACK_PRINCIPAL_MAP_JSON";
pub const TEAMS_APPLICATION_ID_ENV: &str = "FDAI_TEAMS_APPLICATION_ID";
pub const TEAMS_TENANT_ID_ENV: &str = "FDAI_TEAMS_TENANT_ID";
pub const TEAMS_PRINCIPAL_MAP_ENV: &str = "FDAI_TEAMS_PRINCIPAL_MAP_JSON";
pub const TEAMS_SERVICE_URLS_ENV: &str = "FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON";
pub const TEAMS_JWKS_URL_ENV: &str = "FDAI_TEAMS_JWKS_URL";
pub const TEAMS_CLIENT_SECRET_ENV: &str = "FDAI_TEAMS_CLIENT_SECRET";
pub const MANAGED_IDENTITY_CLIENT_ID_ENV: &str = "FDAI_CHANNEL_EDGE_MI_CLIENT_ID";
pub const DEFAULT_HOST: &str = "0.0.0.0";
pub const EXPECTED_DATABASE_ROLE: &str = "fdai_operator";
pub const DEFAULT_SEMANTIC_GROUP: &str = "operator-channel-edge-semantic-v1";
pub const DEFAULT_SEMANTIC_CLIENT_ID: &str = "fdai-operator-channel-edge";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ChannelEdgeConfigurationError {
    pub message: String,
}

impl ChannelEdgeConfigurationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ChannelEdgeConfigurationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ChannelEdgeConfigurationError {}

impl ChannelEdgeEnvironment {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn parse(mut environ: std::collections::BTreeMap<String, String>) -> Result<ChannelEdgeEnvironment, &'static str> {
        let values: std::collections::BTreeMap<String, String> = environ.clone();
        let host: String = ((values.clone()).get(HOST_ENV).cloned().unwrap_or_else(|| String::from(DEFAULT_HOST))).trim().to_string();
        if (host.clone()).is_empty() {
            return Err("HOST_ENV MUST be non-empty");
        }
        let port: i64 = bounded_int(values.clone(), String::from(PORT_ENV), DEFAULT_PORT, 1_i64, 65535_i64).unwrap_or_else(|_| 0_i64);
        let enabled_channels: std::collections::BTreeSet<String> = channels(required(values.clone(), String::from(ENABLED_CHANNELS_ENV)).unwrap_or_else(|_| String::new())).unwrap_or_else(|_| std::collections::BTreeSet::new());
        let database_url: String = required(values.clone(), String::from(DATABASE_URL_ENV)).unwrap_or_else(|_| String::new());
        let database_role: String = required(values.clone(), String::from(DATABASE_ROLE_ENV)).unwrap_or_else(|_| String::new());
        if (database_role.clone()) != (String::from(EXPECTED_DATABASE_ROLE)) {
            return Err("DATABASE_ROLE_ENV MUST be EXPECTED_DATABASE_ROLE");
        }
        let kafka_bootstrap_servers: String = required(values.clone(), String::from(KAFKA_BOOTSTRAP_ENV)).unwrap_or_else(|_| String::new());
        let semantic_request_topic: String = required(values.clone(), String::from(SEMANTIC_REQUEST_TOPIC_ENV)).unwrap_or_else(|_| String::new());
        let semantic_projection_topic: String = required(values.clone(), String::from(SEMANTIC_PROJECTION_TOPIC_ENV)).unwrap_or_else(|_| String::new());
        if (semantic_request_topic.clone()) == (semantic_projection_topic.clone()) {
            return Err("semantic request and projection topics MUST differ");
        }
        let semantic_physical_topic: Option<String> = (Some(((values.clone()).get(SEMANTIC_PHYSICAL_TOPIC_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None);
        let semantic_authentication_receipt_ref_enabled: bool = operator_boolean(values.clone(), String::from(SEMANTIC_AUTHENTICATION_RECEIPT_REF_ENV)).unwrap_or_else(|_| false);
        let attachments_enabled: bool = binary_flag(values.clone(), String::from(ATTACHMENTS_ENABLED_ENV)).unwrap_or_else(|_| false);
        let principal_scopes: std::collections::BTreeMap<String, PrincipalScopeSettings> = principal_scopes(required(values.clone(), String::from(PRINCIPAL_SCOPES_ENV)).unwrap_or_else(|_| String::new())).unwrap_or_else(|_| std::collections::BTreeMap::new());
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn attachment_settings(mut values: std::collections::BTreeMap<String, String>, mut execution_venue: String, mut enabled_channels: std::collections::BTreeSet<String>) -> Result<AttachmentEdgeSettings, &'static str> {
    if !(binary_flag(values.clone(), String::from(ATTACHMENT_SCRATCH_ENCRYPTED_ENV)).unwrap_or_else(|_| false)) {
        return Err("ATTACHMENT_SCRATCH_ENCRYPTED_ENV MUST be 1 when attachments are enabled");
    }
    let intake_origin: String = attachment_origin(required(values.clone(), String::from(ATTACHMENT_INTAKE_ORIGIN_ENV)).unwrap_or_else(|_| String::new()), execution_venue.clone()).unwrap_or_else(|_| String::new());
    let mut slack_files_info_url: Option<String> = None;
    let mut slack_metadata_hosts: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let mut slack_download_hosts: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let mut teams_url_template: Option<String> = None;
    let mut teams_audience: Option<String> = None;
    let mut teams_hosts: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let mut teams_audiences: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    Ok(AttachmentEdgeSettings { intake_origin: intake_origin.clone(), intake_audience: bounded(required(values.clone(), String::from(ATTACHMENT_INTAKE_AUDIENCE_ENV)).unwrap_or_else(|_| String::new()), String::from(ATTACHMENT_INTAKE_AUDIENCE_ENV), 512_i64).unwrap_or_else(|_| String::new()), client_id: attachment_client_id(values.clone(), execution_venue.clone()).unwrap_or_else(|_| String::new()), max_content_bytes: bounded_int(values.clone(), String::from(ATTACHMENT_MAX_BYTES_ENV), (25_i64).saturating_mul((1024_i64).saturating_mul(1024_i64)), 1_i64, (1024_i64).saturating_mul((1024_i64).saturating_mul(1024_i64))).unwrap_or_else(|_| 0_i64), principal_manifest_digest: principal_manifest_digest(required(values.clone(), String::from(PRINCIPAL_SCOPES_ENV)).unwrap_or_else(|_| String::new())).unwrap_or_else(|_| String::new()), slack_files_info_url: slack_files_info_url.clone(), teams_url_template: teams_url_template.clone(), teams_audience: teams_audience.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn attachment_client_id(mut values: std::collections::BTreeMap<String, String>, mut execution_venue: String) -> Result<String, &'static str> {
    let configured: String = bounded(required(values.clone(), String::from(ATTACHMENT_CLIENT_ID_ENV)).unwrap_or_else(|_| String::new()), String::from(ATTACHMENT_CLIENT_ID_ENV), 200_i64).unwrap_or_else(|_| String::new());
    let secret: String = ((values.clone()).get(ATTACHMENT_CLIENT_SECRET_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    let tenant: String = ((values.clone()).get(ATTACHMENT_TENANT_ID_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    Ok(configured.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn slack_settings(mut values: std::collections::BTreeMap<String, String>, mut scopes: std::collections::BTreeMap<String, PrincipalScopeSettings>) -> SlackEdgeSettings {
    let mapping: std::collections::BTreeMap<String, String> = principal_mapping(required(values.clone(), String::from(SLACK_PRINCIPAL_MAP_ENV)).unwrap_or_else(|_| String::new()), scopes.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    SlackEdgeSettings { signing_secret: required(values.clone(), String::from(SLACK_SIGNING_SECRET_ENV)).unwrap_or_else(|_| String::new()), bot_token: required(values.clone(), String::from(SLACK_BOT_TOKEN_ENV)).unwrap_or_else(|_| String::new()), team_id: bounded(required(values.clone(), String::from(SLACK_TEAM_ID_ENV)).unwrap_or_else(|_| String::new()), String::from(SLACK_TEAM_ID_ENV), 200_i64).unwrap_or_else(|_| String::new()), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn teams_settings(mut values: std::collections::BTreeMap<String, String>, mut scopes: std::collections::BTreeMap<String, PrincipalScopeSettings>, mut execution_venue: String) -> Result<TeamsEdgeSettings, &'static str> {
    let mapping: std::collections::BTreeMap<String, String> = principal_mapping(required(values.clone(), String::from(TEAMS_PRINCIPAL_MAP_ENV)).unwrap_or_else(|_| String::new()), scopes.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let service_urls_raw: String = json(required(values.clone(), String::from(TEAMS_SERVICE_URLS_ENV)).unwrap_or_else(|_| String::new())).unwrap_or_else(|_| String::new());
    if (!(false)) || ((service_urls_raw.clone()).is_empty()) {
        return Err("TEAMS_SERVICE_URLS_ENV MUST be a non-empty JSON array");
    }
    let client_secret: Option<String> = (Some(((values.clone()).get(TEAMS_CLIENT_SECRET_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None);
    let managed_identity_client_id: Option<String> = (Some(((values.clone()).get(MANAGED_IDENTITY_CLIENT_ID_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None);
    Ok(TeamsEdgeSettings { application_id: bounded(required(values.clone(), String::from(TEAMS_APPLICATION_ID_ENV)).unwrap_or_else(|_| String::new()), String::from(TEAMS_APPLICATION_ID_ENV), 200_i64).unwrap_or_else(|_| String::new()), tenant_id: bounded(required(values.clone(), String::from(TEAMS_TENANT_ID_ENV)).unwrap_or_else(|_| String::new()), String::from(TEAMS_TENANT_ID_ENV), 200_i64).unwrap_or_else(|_| String::new()), jwks_url: https_url(required(values.clone(), String::from(TEAMS_JWKS_URL_ENV)).unwrap_or_else(|_| String::new()), String::from(TEAMS_JWKS_URL_ENV), false).unwrap_or_else(|_| String::new()), client_secret: client_secret.clone(), managed_identity_client_id: managed_identity_client_id.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn principal_scopes(mut value: String) -> Result<std::collections::BTreeMap<String, PrincipalScopeSettings>, &'static str> {
    let raw: String = json(value.clone()).unwrap_or_else(|_| String::new());
    if (!(false)) || ((raw.clone()).is_empty()) {
        return Err("PRINCIPAL_SCOPES_ENV MUST be a non-empty JSON object");
    }
    let mut scopes: std::collections::BTreeMap<String, PrincipalScopeSettings> = std::collections::BTreeMap::<String, PrincipalScopeSettings>::new();
    Ok(scopes.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn principal_manifest_digest(mut value: String) -> Result<String, &'static str> {
    let raw: String = json(value.clone()).unwrap_or_else(|_| String::new());
    if !(false) {
        return Err("PRINCIPAL_SCOPES_ENV MUST be an object");
    }
    let mut normalized: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>> = std::collections::BTreeMap::<String, std::collections::BTreeMap<String, String>>::new();
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn principal_mapping(mut value: String, mut scopes: std::collections::BTreeMap<String, PrincipalScopeSettings>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let raw: String = json(value.clone()).unwrap_or_else(|_| String::new());
    if (!(false)) || ((raw.clone()).is_empty()) {
        return Err("channel principal mapping MUST be a non-empty object");
    }
    let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn channels(mut value: String) -> Result<std::collections::BTreeSet<String>, &'static str> {
    Ok(std::collections::BTreeSet::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn json(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn unique_object(mut pairs: Vec<(String, String)>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn https_url(mut value: String, mut name: String, mut allow_query: bool) -> Result<String, &'static str> {
    if (!(true)) || ((((value.clone()).len() as i64)) > (2048_i64)) {
        return Err("name MUST contain bounded HTTPS URLs");
    }
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn attachment_origin(mut value: String, mut execution_venue: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn fixed_https_url(mut value: String, mut name: String, mut allowed_hosts: std::collections::BTreeSet<String>) -> Result<String, &'static str> {
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn host_allowlist(mut value: String, mut name: String) -> Result<std::collections::BTreeSet<String>, &'static str> {
    let raw: String = json(value.clone()).unwrap_or_else(|_| String::new());
    if (!(false)) || ((raw.clone()).is_empty()) {
        return Err("name MUST be a non-empty JSON array");
    }
    let mut hosts: Vec<String> = Vec::<String>::new();
    if (((hosts.clone()).len() as i64)) != ((((hosts.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) {
        return Err("name MUST contain unique hosts");
    }
    Ok((hosts.clone()).into_iter().collect::<std::collections::BTreeSet<String>>())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn text_allowlist(mut value: String, mut name: String) -> Result<std::collections::BTreeSet<String>, &'static str> {
    let raw: String = json(value.clone()).unwrap_or_else(|_| String::new());
    Ok(std::collections::BTreeSet::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn required(mut values: std::collections::BTreeMap<String, String>, mut key: String) -> Result<String, &'static str> {
    let value: String = ((values.clone()).get(key.as_str()).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    if (value.clone()).is_empty() {
        return Err("key MUST be non-empty");
    }
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bounded(mut value: String, mut name: String, mut maximum: i64) -> Result<String, &'static str> {
    if ((value.trim().to_string()).is_empty()) || ((((value.clone()).len() as i64)) > (maximum)) {
        return Err("name MUST be bounded and non-empty");
    }
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bounded_int(mut values: std::collections::BTreeMap<String, String>, mut key: String, mut default: i64, mut minimum: i64, mut maximum: i64) -> Result<i64, &'static str> {
    let raw: String = ((values.clone()).get(key.as_str()).cloned().unwrap_or_else(|| (default).to_string())).trim().to_string();
    let value: i64 = (raw.clone()).trim().parse::<i64>().unwrap_or(0);
    if !(((minimum) <= (value)) && ((value) <= (maximum))) {
        return Err("key is outside the allowed range");
    }
    Ok(value)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn operator_boolean(mut values: std::collections::BTreeMap<String, String>, mut key: String) -> Result<bool, &'static str> {
    let raw: String = (((values.clone()).get(key.as_str()).cloned().unwrap_or_else(|| String::from("0"))).trim().to_string()).to_lowercase();
    if matches!(raw.as_str(), "1" | "true" | "yes" | "on") {
        return Ok(true);
    }
    if matches!(raw.as_str(), "0" | "false" | "no" | "off") {
        return Ok(false);
    }
    Err("key MUST be a boolean")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn binary_flag(mut values: std::collections::BTreeMap<String, String>, mut key: String) -> Result<bool, &'static str> {
    let value: String = ((values.clone()).get(key.as_str()).cloned().unwrap_or_else(|| String::from("0"))).trim().to_string();
    if !(matches!(value.as_str(), "0" | "1")) {
        return Err("key MUST be 0 or 1");
    }
    Ok((value.clone()) == (String::from("1")))
}

pub const PUBLIC_EXPORTS: &[&str] = &["AttachmentEdgeSettings", "ChannelEdgeConfigurationError", "ChannelEdgeEnvironment", "PrincipalScopeSettings", "SlackEdgeSettings", "TeamsEdgeSettings"];
