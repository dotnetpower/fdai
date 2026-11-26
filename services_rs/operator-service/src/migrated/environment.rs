use std::collections::BTreeMap;
pub const DEFAULT_PORT: i64 = 8000;
pub const DEFAULT_DATABASE_STATEMENT_TIMEOUT_MS: i64 = 20000;
pub const DEFAULT_DATABASE_CONNECT_TIMEOUT_S: i64 = 10;
pub const DEFAULT_NARRATOR_PROBE_INTERVAL_SECONDS: i64 = 300;
pub const MIN_NARRATOR_PROBE_INTERVAL_SECONDS: i64 = 30;
pub const MAX_NARRATOR_PROBE_INTERVAL_SECONDS: i64 = 3600;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperatorEnvironment {
    pub values: BTreeMap<String, String>,
    pub host: String,
    pub port: i64,
    pub tenant_id: String,
    pub audience: String,
    pub issuer: String,
    pub jwks_uri: String,
    pub group_ids: BTreeMap<String, String>,
    pub cors_allow_origins: Vec<String>,
    pub database_url: Option<String>,
    pub database_role: Option<String>,
    pub database_statement_timeout_ms: i64,
    pub database_connect_timeout_s: i64,
    pub local_azure_narrator: bool,
    pub local_azure_cli_auth: bool,
    pub narrator_probe_interval_seconds: i64,
    pub kafka_bootstrap_servers: Option<String>,
    pub hil_decision_topic: Option<String>,
    pub notification_receipt_topic: Option<String>,
    pub stage_topic: String,
    pub live_stage_consumer_group_id: String,
    pub semantic_request_topic: Option<String>,
    pub semantic_projection_topic: Option<String>,
    pub semantic_physical_topic: Option<String>,
    pub semantic_outbox_namespace: Option<String>,
    pub semantic_authentication_receipt_ref_enabled: bool,
    pub semantic_dialogue_state_enabled: bool,
    pub semantic_consumer_group_id: String,
    pub semantic_kafka_client_id: String,
    pub read_investigation_request_topic: Option<String>,
    pub read_investigation_completion_topic: Option<String>,
    pub read_investigation_completion_consumer_group_id: Option<String>,
    pub background_task_projection_topic: Option<String>,
    pub background_task_projection_consumer_group_id: Option<String>,
    pub managed_identity_client_id: Option<String>,
    pub test_context_grant_registry_json: Option<String>,
    pub operator_request_operator_signing_seed: Option<String>,
    pub operator_request_receipt_producer_id: Option<String>,
    pub operator_request_receipt_ttl_seconds: i64,
    pub product_profile: String,
}

pub const HOST_ENV: &str = "FDAI_OPERATOR_SERVICE_HOST";
pub const PORT_ENV: &str = "FDAI_OPERATOR_SERVICE_PORT";
pub const TENANT_ENV: &str = "FDAI_ENTRA_TENANT_ID";
pub const AUDIENCE_ENV: &str = "FDAI_API_AUDIENCE";
pub const ISSUER_ENV: &str = "FDAI_ENTRA_ISSUER";
pub const JWKS_URI_ENV: &str = "FDAI_ENTRA_JWKS_URI";
pub const CORS_ORIGINS_ENV: &str = "FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS";
pub const DATABASE_URL_ENV: &str = "FDAI_DATABASE_URL";
pub const DATABASE_ROLE_ENV: &str = "FDAI_DATABASE_ROLE";
pub const DATABASE_STATEMENT_TIMEOUT_ENV: &str = "FDAI_OPERATOR_DATABASE_STATEMENT_TIMEOUT_MS";
pub const DATABASE_CONNECT_TIMEOUT_ENV: &str = "FDAI_OPERATOR_DATABASE_CONNECT_TIMEOUT_S";
pub const EXPECTED_DATABASE_ROLE: &str = "fdai_operator";
pub const LOCAL_AZURE_NARRATOR_ENV: &str = "FDAI_OPERATOR_SERVICE_LOCAL_AZURE_NARRATOR";
pub const LOCAL_AZURE_CLI_AUTH_ENV: &str = "FDAI_OPERATOR_API_LOCAL_AZURE_CLI";
pub const LOCAL_AZURE_CLI_AUTH_CONFIRM_ENV: &str = "FDAI_OPERATOR_API_LOCAL_AZURE_CLI_CONFIRM";
pub const LOCAL_ENTRA_AUTH_ENV: &str = "FDAI_OPERATOR_API_LOCAL_ENTRA";
pub const DEV_MODE_ENV: &str = "FDAI_OPERATOR_API_DEV_MODE";
pub const NARRATOR_PROBE_INTERVAL_ENV: &str = "FDAI_NARRATOR_PROBE_INTERVAL_SECONDS";
pub const KAFKA_BOOTSTRAP_SERVERS_ENV: &str = "FDAI_KAFKA_BOOTSTRAP_SERVERS";
pub const HIL_DECISION_TOPIC_ENV: &str = "FDAI_HIL_DECISION_TOPIC";
pub const NOTIFICATION_RECEIPT_TOPIC_ENV: &str = "FDAI_NOTIFICATION_RECEIPT_TOPIC";
pub const NOTIFICATION_RECEIPT_SECRET_ENV: &str = "FDAI_NOTIFICATION_RECEIPT_SECRET";
pub const STAGE_TOPIC_ENV: &str = "FDAI_STAGE_TOPIC";
pub const LIVE_STAGE_CONSUMER_GROUP_ENV: &str = "FDAI_LIVE_STAGE_CONSUMER_GROUP_ID";
pub const SEMANTIC_REQUEST_TOPIC_ENV: &str = "FDAI_SEMANTIC_TURN_REQUEST_TOPIC";
pub const SEMANTIC_PROJECTION_TOPIC_ENV: &str = "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC";
pub const SEMANTIC_PHYSICAL_TOPIC_ENV: &str = "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC";
pub const SEMANTIC_OUTBOX_NAMESPACE_ENV: &str = "FDAI_SEMANTIC_TURN_OUTBOX_NAMESPACE";
pub const SEMANTIC_AUTHENTICATION_RECEIPT_REF_ENV: &str = "FDAI_SEMANTIC_AUTHENTICATION_RECEIPT_REF_ENABLED";
pub const SEMANTIC_DIALOGUE_STATE_ENV: &str = "FDAI_SEMANTIC_DIALOGUE_STATE_ENABLED";
pub const SEMANTIC_CONSUMER_GROUP_ENV: &str = "FDAI_SEMANTIC_TURN_CONSUMER_GROUP_ID";
pub const SEMANTIC_KAFKA_CLIENT_ID_ENV: &str = "FDAI_SEMANTIC_TURN_KAFKA_CLIENT_ID";
pub const READ_INVESTIGATION_REQUEST_TOPIC_ENV: &str = "FDAI_READ_INVESTIGATION_REQUEST_TOPIC";
pub const READ_INVESTIGATION_COMPLETION_TOPIC_ENV: &str = "FDAI_READ_INVESTIGATION_COMPLETION_TOPIC";
pub const BACKGROUND_TASK_PROJECTION_TOPIC_ENV: &str = "FDAI_BACKGROUND_TASK_PROJECTION_TOPIC";
pub const BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP_ENV: &str = "FDAI_BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP_ID";
pub const MANAGED_IDENTITY_CLIENT_ID_ENV: &str = "FDAI_COMMAND_MI_CLIENT_ID";
pub const TEST_CONTEXT_GRANT_REGISTRY_JSON_ENV: &str = "FDAI_TEST_CONTEXT_GRANT_REGISTRY_JSON";
pub const OPERATOR_REQUEST_OPERATOR_SIGNING_SEED_ENV: &str = "FDAI_OPERATOR_REQUEST_OPERATOR_SIGNING_SEED";
pub const OPERATOR_REQUEST_RECEIPT_PRODUCER_ID_ENV: &str = "FDAI_OPERATOR_REQUEST_RECEIPT_PRODUCER_ID";
pub const OPERATOR_REQUEST_RECEIPT_TTL_SECONDS_ENV: &str = "FDAI_OPERATOR_REQUEST_RECEIPT_TTL_SECONDS";
pub const PRODUCT_PROFILE_JSON_ENV: &str = "FDAI_PRODUCT_PROFILE_JSON";
pub const DEFAULT_HOST: &str = "0.0.0.0";
pub const DEFAULT_SEMANTIC_CONSUMER_GROUP: &str = "operator-semantic-turn-v1";
pub const DEFAULT_SEMANTIC_KAFKA_CLIENT_ID: &str = "fdai-operator-service";
pub const DEFAULT_STAGE_TOPIC: &str = "fdai.pipeline.stages";
pub const DEFAULT_HIL_DECISION_TOPIC: &str = "fdai.hil.decisions";
pub const DEFAULT_LIVE_STAGE_CONSUMER_GROUP: &str = "fdai-operator-live-stage-v1";
pub const DEFAULT_READ_INVESTIGATION_COMPLETION_TOPIC: &str = "core.read-investigation.completions";
pub const DEFAULT_READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP: &str = "operator-read-investigation-completion-v1";
pub const SEMANTIC_OUTBOX_NAMESPACE_PATTERN: &str = "^[a-z0-9][a-z0-9._-]{0,63}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct OperatorServiceConfigurationError {
    pub message: String,
}

impl OperatorServiceConfigurationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for OperatorServiceConfigurationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for OperatorServiceConfigurationError {}

impl OperatorEnvironment {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn parse(mut environ: std::collections::BTreeMap<String, String>) -> Result<OperatorEnvironment, &'static str> {
        let values: std::collections::BTreeMap<String, String> = environ.clone();
        let host: String = ((values.clone()).get(HOST_ENV).cloned().unwrap_or_else(|| String::from(DEFAULT_HOST))).trim().to_string();
        if (host.clone()).is_empty() {
            return Err("HOST_ENV MUST be non-empty");
        }
        let raw_port: String = ((values.clone()).get(PORT_ENV).cloned().unwrap_or_else(|| (DEFAULT_PORT).to_string())).trim().to_string();
        let port: i64 = (raw_port.clone()).trim().parse::<i64>().unwrap_or(0);
        if !(((1_i64) <= (port)) && ((port) <= (65535_i64))) {
            return Err("PORT_ENV MUST be between 1 and 65535");
        }
        let tenant_id: String = require(values.clone(), String::from(TENANT_ENV)).unwrap_or_else(|_| String::new());
        let audience: String = require(values.clone(), String::from(AUDIENCE_ENV)).unwrap_or_else(|_| String::new());
        let issuer: String = { let _a = ((values.clone()).get(ISSUER_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string(); if !_a.is_empty() { _a } else { format!("https://login.microsoftonline.com/{}/v2.0", tenant_id.clone()) } };
        let jwks_uri: String = { let _a = ((values.clone()).get(JWKS_URI_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string(); if !_a.is_empty() { _a } else { format!("https://login.microsoftonline.com/{}/discovery/v2.0/keys", tenant_id.clone()) } };
        let database_url: Option<String> = (Some(((values.clone()).get(DATABASE_URL_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None);
        let database_role: Option<String> = (Some(((values.clone()).get(DATABASE_ROLE_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None);
        if (database_url.is_none()) && (database_role.is_some()) {
            return Err("DATABASE_ROLE_ENV MUST be unset when DATABASE_URL_ENV is unset");
        }
        if (database_url.is_some()) && ((database_role.clone()) != Some(String::from(EXPECTED_DATABASE_ROLE))) {
            return Err("DATABASE_ROLE_ENV MUST be EXPECTED_DATABASE_ROLE");
        }
        let database_statement_timeout_ms: i64 = positive_int(values.clone(), String::from(DATABASE_STATEMENT_TIMEOUT_ENV), DEFAULT_DATABASE_STATEMENT_TIMEOUT_MS).unwrap_or_else(|_| 0_i64);
        let database_connect_timeout_s: i64 = positive_int(values.clone(), String::from(DATABASE_CONNECT_TIMEOUT_ENV), DEFAULT_DATABASE_CONNECT_TIMEOUT_S).unwrap_or_else(|_| 0_i64);
        let local_azure_narrator: bool = boolean(values.clone(), String::from(LOCAL_AZURE_NARRATOR_ENV), false).unwrap_or_else(|_| false);
        let local_azure_cli_auth: bool = boolean(values.clone(), String::from(LOCAL_AZURE_CLI_AUTH_ENV), false).unwrap_or_else(|_| false);
        let local_azure_cli_auth_confirmed: bool = boolean(values.clone(), String::from(LOCAL_AZURE_CLI_AUTH_CONFIRM_ENV), false).unwrap_or_else(|_| false);
        let local_entra_auth: bool = boolean(values.clone(), String::from(LOCAL_ENTRA_AUTH_ENV), false).unwrap_or_else(|_| false);
        let dev_mode: bool = boolean(values.clone(), String::from(DEV_MODE_ENV), false).unwrap_or_else(|_| false);
        if (local_azure_cli_auth) != (local_azure_cli_auth_confirmed) {
            return Err("LOCAL_AZURE_CLI_AUTH_ENV and  fLOCAL_AZURE_CLI_AUTH_CONFIRM_ENV MUST be ");
        }
        if local_azure_cli_auth {
            if ((((values.clone()).get("RUNTIME_ENV").cloned().unwrap_or_else(|| String::from(""))).trim().to_string()).to_lowercase()) != (String::from("dev")) {
                return Err("LOCAL_AZURE_CLI_AUTH_ENV requires RUNTIME_ENVdev");
            }
            if (dev_mode) || (local_entra_auth) {
                return Err("LOCAL_AZURE_CLI_AUTH_ENV MUST NOT be combined with  fDEV_MODE_ENV or LOC");
            }
        }
        let narrator_probe_interval_seconds: i64 = bounded_int(values.clone(), String::from(NARRATOR_PROBE_INTERVAL_ENV), DEFAULT_NARRATOR_PROBE_INTERVAL_SECONDS, MIN_NARRATOR_PROBE_INTERVAL_SECONDS, MAX_NARRATOR_PROBE_INTERVAL_SECONDS).unwrap_or_else(|_| 0_i64);
        if (local_azure_narrator) && (((((values.clone()).get("RUNTIME_ENV").cloned().unwrap_or_else(|| String::from(""))).trim().to_string()).to_lowercase()) != (String::from("dev"))) {
            return Err("LOCAL_AZURE_NARRATOR_ENV requires RUNTIME_ENVdev");
        }
        let kafka_bootstrap_servers: Option<String> = (Some(((values.clone()).get(KAFKA_BOOTSTRAP_SERVERS_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None);
        let explicit_hil_decision_topic: String = ((values.clone()).get(HIL_DECISION_TOPIC_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
        if (!(explicit_hil_decision_topic.clone()).is_empty()) && (kafka_bootstrap_servers.is_none()) {
            return Err("HIL_DECISION_TOPIC_ENV requires KAFKA_BOOTSTRAP_SERVERS_ENV");
        }
        let hil_decision_topic: Option<String> = if kafka_bootstrap_servers.is_some() { (Some(explicit_hil_decision_topic.clone())).or_else(|| Some(String::from(DEFAULT_HIL_DECISION_TOPIC))) } else { None };
        let explicit_notification_receipt_topic: String = ((values.clone()).get(NOTIFICATION_RECEIPT_TOPIC_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
        if (!(explicit_notification_receipt_topic.clone()).is_empty()) && (kafka_bootstrap_servers.is_none()) {
            return Err("NOTIFICATION_RECEIPT_TOPIC_ENV requires KAFKA_BOOTSTRAP_SERVERS_ENV");
        }
        let stage_topic: String = { let _a = ((values.clone()).get(STAGE_TOPIC_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string(); if !_a.is_empty() { _a } else { String::from(DEFAULT_STAGE_TOPIC) } };
        let live_stage_consumer_group_id: String = { let _a = ((values.clone()).get(LIVE_STAGE_CONSUMER_GROUP_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string(); if !_a.is_empty() { _a } else { String::from(DEFAULT_LIVE_STAGE_CONSUMER_GROUP) } };
        let semantic_request_topic: Option<String> = (Some(((values.clone()).get(SEMANTIC_REQUEST_TOPIC_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None);
        let semantic_projection_topic: Option<String> = (Some(((values.clone()).get(SEMANTIC_PROJECTION_TOPIC_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None);
        let semantic_physical_topic: Option<String> = (Some(((values.clone()).get(SEMANTIC_PHYSICAL_TOPIC_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None);
        let semantic_outbox_namespace: Option<String> = (Some(((values.clone()).get(SEMANTIC_OUTBOX_NAMESPACE_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None);
        let semantic_authentication_receipt_ref_enabled: bool = boolean(values.clone(), String::from(SEMANTIC_AUTHENTICATION_RECEIPT_REF_ENV), false).unwrap_or_else(|_| false);
        let semantic_dialogue_state_enabled: bool = boolean(values.clone(), String::from(SEMANTIC_DIALOGUE_STATE_ENV), false).unwrap_or_else(|_| false);
        if (semantic_outbox_namespace.is_some()) && (database_url.is_none()) {
            return Err("SEMANTIC_OUTBOX_NAMESPACE_ENV requires DATABASE_URL_ENV");
        }
        if (hil_decision_topic.is_some()) && ((std::collections::BTreeSet::from([(semantic_request_topic.clone()).unwrap_or_default(), (semantic_projection_topic.clone()).unwrap_or_default(), (semantic_physical_topic.clone()).unwrap_or_default()])).contains(((hil_decision_topic.clone()).unwrap_or_default()).as_str())) {
            return Err("HIL_DECISION_TOPIC_ENV MUST be distinct from semantic topics");
        }
        if (local_azure_narrator) && (kafka_bootstrap_servers.is_some()) {
            return Err("LOCAL_AZURE_NARRATOR_ENV MUST be disabled when semantic Kafka transport ");
        }
        if (!(((values.clone()).get("FDAI_CHATOPS_WEBHOOK_SECRET").cloned().unwrap_or_else(|| String::from(""))).trim().to_string()).is_empty()) && ((database_url.is_none()) || ((kafka_bootstrap_servers.is_none()) || (hil_decision_topic.is_none()))) {
            return Err("HIL callback requires PostgreSQL and configured Kafka decision transport");
        }
        let semantic_consumer_group_id: String = { let _a = ((values.clone()).get(SEMANTIC_CONSUMER_GROUP_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string(); if !_a.is_empty() { _a } else { String::from(DEFAULT_SEMANTIC_CONSUMER_GROUP) } };
        let semantic_kafka_client_id: String = { let _a = ((values.clone()).get(SEMANTIC_KAFKA_CLIENT_ID_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string(); if !_a.is_empty() { _a } else { String::from(DEFAULT_SEMANTIC_KAFKA_CLIENT_ID) } };
        let read_investigation_request_topic: Option<String> = (Some(((values.clone()).get(READ_INVESTIGATION_REQUEST_TOPIC_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None);
        if (read_investigation_request_topic.is_some()) && (kafka_bootstrap_servers.is_none()) {
            return Err("READ_INVESTIGATION_REQUEST_TOPIC_ENV requires KAFKA_BOOTSTRAP_SERVERS_EN");
        }
        if (read_investigation_request_topic.is_some()) && ((std::collections::BTreeSet::from([(semantic_request_topic.clone()).unwrap_or_default(), (semantic_projection_topic.clone()).unwrap_or_default(), (semantic_physical_topic.clone()).unwrap_or_default(), (hil_decision_topic.clone()).unwrap_or_default()])).contains(((read_investigation_request_topic.clone()).unwrap_or_default()).as_str())) {
            return Err("READ_INVESTIGATION_REQUEST_TOPIC_ENV MUST be distinct from semantic topi");
        }
        let explicit_completion_topic: String = ((values.clone()).get(READ_INVESTIGATION_COMPLETION_TOPIC_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
        let read_investigation_completion_topic: Option<String> = if kafka_bootstrap_servers.is_some() { (Some(explicit_completion_topic.clone())).or_else(|| Some(String::from(DEFAULT_READ_INVESTIGATION_COMPLETION_TOPIC))) } else { None };
        if (read_investigation_completion_topic.is_some()) && ((std::collections::BTreeSet::from([(semantic_request_topic.clone()).unwrap_or_default(), (semantic_projection_topic.clone()).unwrap_or_default(), (semantic_physical_topic.clone()).unwrap_or_default(), (read_investigation_request_topic.clone()).unwrap_or_default(), (hil_decision_topic.clone()).unwrap_or_default()])).contains(((read_investigation_completion_topic.clone()).unwrap_or_default()).as_str())) {
            return Err("READ_INVESTIGATION_COMPLETION_TOPIC_ENV MUST be distinct from other topi");
        }
        let explicit_background_task_projection_topic: String = ((values.clone()).get(BACKGROUND_TASK_PROJECTION_TOPIC_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
        let explicit_background_task_projection_group: String = ((values.clone()).get(BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
        if ((!(explicit_background_task_projection_topic.clone()).is_empty()) || (!(explicit_background_task_projection_group.clone()).is_empty())) && (kafka_bootstrap_servers.is_none()) {
            return Err("background task projection transport requires KAFKA_BOOTSTRAP_SERVERS_EN");
        }
        let managed_identity_client_id: Option<String> = (Some(((values.clone()).get(MANAGED_IDENTITY_CLIENT_ID_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None);
        let test_context_grant_registry_json: Option<String> = (Some(((values.clone()).get(TEST_CONTEXT_GRANT_REGISTRY_JSON_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None);
        let operator_request_operator_signing_seed: Option<String> = (Some(((values.clone()).get(OPERATOR_REQUEST_OPERATOR_SIGNING_SEED_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None);
        let operator_request_receipt_producer_id: Option<String> = (Some(((values.clone()).get(OPERATOR_REQUEST_RECEIPT_PRODUCER_ID_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None);
        let operator_request_receipt_ttl_seconds: i64 = bounded_int(values.clone(), String::from(OPERATOR_REQUEST_RECEIPT_TTL_SECONDS_ENV), 300_i64, 1_i64, 900_i64).unwrap_or_else(|_| 0_i64);
        if (operator_request_operator_signing_seed.is_none()) != (operator_request_receipt_producer_id.is_none()) {
            return Err("OPERATOR_REQUEST_OPERATOR_SIGNING_SEED_ENV and  fOPERATOR_REQUEST_RECEIP");
        }
        let product_profile: String = product_profile(values.clone()).unwrap_or_else(|_| String::new());
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn require(mut environ: std::collections::BTreeMap<String, String>, mut key: String) -> Result<String, &'static str> {
    let value: String = ((environ.clone()).get(key.as_str()).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    if (value.clone()).is_empty() {
        return Err("key MUST be non-empty");
    }
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn positive_int(mut environ: std::collections::BTreeMap<String, String>, mut key: String, mut default: i64) -> Result<i64, &'static str> {
    let raw: String = ((environ.clone()).get(key.as_str()).cloned().unwrap_or_else(|| (default).to_string())).trim().to_string();
    let value: i64 = (raw.clone()).trim().parse::<i64>().unwrap_or(0);
    if (value) < (1_i64) {
        return Err("key MUST be positive");
    }
    Ok(value)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bounded_int(mut environ: std::collections::BTreeMap<String, String>, mut key: String, mut default: i64, mut minimum: i64, mut maximum: i64) -> Result<i64, &'static str> {
    let value: i64 = positive_int(environ.clone(), key.clone(), default).unwrap_or_else(|_| 0_i64);
    if !(((minimum) <= (value)) && ((value) <= (maximum))) {
        return Err("key MUST be in minimum maximum");
    }
    Ok(value)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn boolean(mut environ: std::collections::BTreeMap<String, String>, mut key: String, mut default: bool) -> Result<bool, &'static str> {
    let raw: String = (((environ.clone()).get(key.as_str()).cloned().unwrap_or_else(|| (default).to_string())).trim().to_string()).to_lowercase();
    if matches!(raw.as_str(), "1" | "true" | "yes" | "on") {
        return Ok(true);
    }
    if matches!(raw.as_str(), "0" | "false" | "no" | "off") {
        return Ok(false);
    }
    Err("key MUST be a boolean")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn product_profile(mut environ: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    let raw: String = ((environ.clone()).get(PRODUCT_PROFILE_JSON_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    Ok(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["AUDIENCE_ENV", "BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP_ENV", "BACKGROUND_TASK_PROJECTION_TOPIC_ENV", "CORS_ORIGINS_ENV", "DATABASE_CONNECT_TIMEOUT_ENV", "DATABASE_ROLE_ENV", "DATABASE_STATEMENT_TIMEOUT_ENV", "DATABASE_URL_ENV", "DEV_MODE_ENV", "DEFAULT_HOST", "DEFAULT_NARRATOR_PROBE_INTERVAL_SECONDS", "DEFAULT_PORT", "EXPECTED_DATABASE_ROLE", "GROUP_ENV", "HOST_ENV", "ISSUER_ENV", "KAFKA_BOOTSTRAP_SERVERS_ENV", "LIVE_STAGE_CONSUMER_GROUP_ENV", "STAGE_TOPIC_ENV", "LOCAL_AZURE_NARRATOR_ENV", "LOCAL_AZURE_CLI_AUTH_ENV", "LOCAL_AZURE_CLI_AUTH_CONFIRM_ENV", "LOCAL_ENTRA_AUTH_ENV", "MAX_NARRATOR_PROBE_INTERVAL_SECONDS", "MANAGED_IDENTITY_CLIENT_ID_ENV", "MIN_NARRATOR_PROBE_INTERVAL_SECONDS", "NARRATOR_PROBE_INTERVAL_ENV", "JWKS_URI_ENV", "PORT_ENV", "PRODUCT_PROFILE_JSON_ENV", "READ_INVESTIGATION_REQUEST_TOPIC_ENV", "READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP_ENV", "READ_INVESTIGATION_COMPLETION_TOPIC_ENV", "SEMANTIC_CONSUMER_GROUP_ENV", "SEMANTIC_KAFKA_CLIENT_ID_ENV", "SEMANTIC_PROJECTION_TOPIC_ENV", "SEMANTIC_PHYSICAL_TOPIC_ENV", "SEMANTIC_OUTBOX_NAMESPACE_ENV", "SEMANTIC_AUTHENTICATION_RECEIPT_REF_ENV", "SEMANTIC_REQUEST_TOPIC_ENV", "TENANT_ENV", "TEST_CONTEXT_GRANT_REGISTRY_JSON_ENV", "OperatorEnvironment", "OperatorServiceConfigurationError"];
