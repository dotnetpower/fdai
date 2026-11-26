pub const RESOURCE_ID: &str = "/subscriptions/[^/]+/resourceGroups/[^/]+/providers/[^/]+/.+";
pub const IMAGE: &str = "[^\\s]+@sha256:[0-9a-f]{64}";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct OperatorTfvarsRecoveryError {
    pub message: String,
}

impl OperatorTfvarsRecoveryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for OperatorTfvarsRecoveryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for OperatorTfvarsRecoveryError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn recover_operator_tfvars(mut app: std::collections::BTreeMap<String, String>, mut platform: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let properties: std::collections::BTreeMap<String, String> = object(String::new(), String::from("Operator properties")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let configuration: std::collections::BTreeMap<String, String> = object(String::new(), String::from("Operator configuration")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let template: std::collections::BTreeMap<String, String> = object(String::new(), String::from("Operator template")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let containers: Vec<std::collections::BTreeMap<String, String>> = objects(String::new(), String::from("Operator containers")).unwrap_or_else(|_| Vec::new());
    if (((containers.clone()).len() as i64)) != (1_i64) {
        return Err("Operator must have exactly one container");
    }
    let image: String = text(String::new(), String::from("Operator image")).unwrap_or_else(|_| String::new());
    let environment: std::collections::BTreeMap<String, String> = environment(String::new()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    if ((environment.clone()).get("FDAI_EXECUTION_VENUE").cloned()) != Some(String::from("deployed")) {
        return Err("Operator execution venue is not deployed");
    }
    let identities: std::collections::BTreeMap<String, String> = identities(String::new()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let runtime_resource_id: String = identity_for_client(identities.clone(), String::new(), String::from("runtime")).unwrap_or_else(|_| String::new());
    let command_resource_id: String = identity_for_client(identities.clone(), String::new(), String::from("command")).unwrap_or_else(|_| String::new());
    if ((runtime_resource_id.clone()).to_lowercase()) == ((command_resource_id.clone()).to_lowercase()) {
        return Err("Operator runtime and command identities must differ");
    }
    let secrets: std::collections::BTreeMap<String, String> = secrets(String::new()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let database_secret: String = secret_reference(secrets.clone(), String::from("database-dsn")).unwrap_or_else(|_| String::new());
    let platform_cost_secret: String = secret_id(String::new(), String::from("Cost pseudonym key")).unwrap_or_else(|_| String::new());
    let current_cost_secret: Option<String> = (secrets.clone()).get("cost-pseudonym-key").cloned();
    if (current_cost_secret.is_some()) && ((current_cost_secret.clone()) != Some(platform_cost_secret.clone())) {
        return Err("deployed Cost pseudonym key differs from the platform-owned binding");
    }
    let resource_group: String = text(String::new(), String::from("platform resource group")).unwrap_or_else(|_| String::new());
    if ((app.clone()).get("resourceGroup").cloned()) != Some(resource_group.clone()) {
        return Err("Operator resource group differs from platform state");
    }
    let environment_id: String = resource_id(String::new(), String::from("Container Apps environment")).unwrap_or_else(|_| String::new());
    if (((properties.clone()).get("managedEnvironmentId").cloned().unwrap_or_else(|| String::from(""))).to_lowercase()) != ((environment_id.clone()).to_lowercase()) {
        return Err("Operator Container Apps environment differs from platform state");
    }
    let kafka_bootstrap: String = text(String::new(), String::from("Kafka bootstrap servers")).unwrap_or_else(|_| String::new());
    let mut recovered: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("name"), text(String::new(), String::from("Operator name")).unwrap_or_else(|_| String::new())), (String::from("platform"), String::new()), (String::from("identity"), String::new()), (String::from("event_topics"), String::new()), (String::from("notification_receipt_secret_id"), (secrets.clone()).get("notification-receipt-secret").cloned().unwrap_or_else(|| String::from(""))), (String::from("cost_pseudonym_key_secret_id"), platform_cost_secret.clone()), (String::from("database"), String::new()), (String::from("health"), String::new()), (String::from("rollback"), String::new()), (String::from("runtime_env"), String::new()), (String::from("auth"), String::new()), (String::from("rbac"), String::new()), (String::from("cors_allow_origins"), String::new()), (String::from("scaling"), String::new()), (String::from("hil_callback"), String::new()), (String::from("tags"), String::new())]);
    let runtime_caller: Option<String> = (environment.clone()).get("FDAI_RUNTIME_CALL_CALLER_RESOURCE_ID").cloned();
    let runtime_target: Option<String> = (environment.clone()).get("FDAI_RUNTIME_CALL_TARGET_RESOURCE_ID").cloned();
    Ok(recovered.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn environment(mut value: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    for item in objects(value.clone(), String::from("Operator environment")).unwrap_or_else(|_| Vec::new()) {
        let name: String = text(String::new(), String::from("Operator environment name")).unwrap_or_else(|_| String::new());
        if (result.clone()).contains_key(name.as_str()) {
            return Err("Operator environment contains duplicate name");
        }
        if (item.clone()).contains_key("secretRef") {
            continue;
        }
        result.insert(name.clone(), text(String::new(), format!("Operator environment {}", name.clone())).unwrap_or_else(|_| String::new()));
    }
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn identities(mut value: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let identity: std::collections::BTreeMap<String, String> = object(value.clone(), String::from("Operator identity")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let raw: std::collections::BTreeMap<String, String> = object(String::new(), String::from("Operator user-assigned identities")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    for (resource_id, binding) in raw.clone() {
        let client_id: String = text(String::new(), String::from("identity client")).unwrap_or_else(|_| String::new());
        if (result.clone()).contains_key(((client_id.clone()).to_lowercase()).as_str()) {
            return Err("Operator identity client id is duplicated");
        }
    }
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn identity_for_client(mut identities: std::collections::BTreeMap<String, String>, mut client_id: String, mut label: String) -> Result<String, &'static str> {
    if identities.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn secrets(mut value: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    for item in objects(value.clone(), String::from("Operator secrets")).unwrap_or_else(|_| Vec::new()) {
        let name: String = text(String::new(), String::from("Operator secret name")).unwrap_or_else(|_| String::new());
        if (result.clone()).contains_key(name.as_str()) {
            return Err("Operator secrets contain duplicate name");
        }
        result.insert(name.clone(), secret_id(String::new(), format!("Operator secret {}", name.clone())).unwrap_or_else(|_| String::new()));
    }
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn secret_reference(mut secrets: std::collections::BTreeMap<String, String>, mut name: String) -> Result<String, &'static str> {
    if secrets.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn health(mut container: std::collections::BTreeMap<String, String>, mut configuration: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let probes: Vec<std::collections::BTreeMap<String, String>> = objects(String::new(), String::from("Operator probes")).unwrap_or_else(|_| Vec::new());
    let mut paths: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    let values: std::collections::BTreeMap<String, i64> = std::collections::BTreeMap::<String, i64>::new();
    let ingress: std::collections::BTreeMap<String, String> = object(String::new(), String::from("Operator ingress")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    Ok(std::collections::BTreeMap::from([(String::from("port"), String::new()), (String::from("interval_seconds"), String::new()), (String::from("timeout_seconds"), String::new()), (String::from("failure_count_threshold"), String::new()), (String::from("startup_failure_count"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn scaling(mut template: std::collections::BTreeMap<String, String>, mut container: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    let scale: std::collections::BTreeMap<String, String> = object(String::new(), String::from("Operator scale")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let resources: std::collections::BTreeMap<String, String> = object(String::new(), String::from("Operator resources")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    std::collections::BTreeMap::from([(String::from("min_replicas"), String::new()), (String::from("max_replicas"), String::new()), (String::from("cpu"), String::new()), (String::from("memory"), text(String::new(), String::from("Operator memory")).unwrap_or_else(|_| String::new()))])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn hil_callback(mut environment: std::collections::BTreeMap<String, String>, mut secrets: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let enabled: bool = (secrets.clone()).contains_key("hil-callback-signing-secret");
    let teams_application_id: String = (environment.clone()).get("FDAI_TEAMS_APPLICATION_ID").cloned().unwrap_or_else(|| String::from(""));
    let slack_team_id: String = (environment.clone()).get("FDAI_SLACK_TEAM_ID").cloned().unwrap_or_else(|| String::from(""));
    if (enabled) && (!((!(teams_application_id.clone()).is_empty()) || (!(slack_team_id.clone()).is_empty()))) {
        return Err("enabled HIL callback has no channel binding");
    }
    Ok(std::collections::BTreeMap::from([(String::from("enabled"), String::new()), (String::from("signing_secret_id"), (secrets.clone()).get("hil-callback-signing-secret").cloned().unwrap_or_else(|| String::from(""))), (String::from("teams_application_id"), teams_application_id.clone()), (String::from("teams_tenant_id"), (environment.clone()).get("FDAI_TEAMS_TENANT_ID").cloned().unwrap_or_else(|| String::from(""))), (String::from("teams_approval_team_id"), (environment.clone()).get("FDAI_TEAMS_APPROVAL_TEAM_ID").cloned().unwrap_or_else(|| String::from(""))), (String::from("teams_approval_channel_id"), (environment.clone()).get("FDAI_TEAMS_APPROVAL_CHANNEL_ID").cloned().unwrap_or_else(|| String::from(""))), (String::from("teams_allowed_service_urls"), (environment.clone()).get("FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON").cloned().unwrap_or_else(|| String::from(""))), (String::from("teams_jwks_url"), (environment.clone()).get("FDAI_TEAMS_JWKS_URL").cloned().unwrap_or_else(|| String::from(""))), (String::from("teams_principal_map_secret_id"), (secrets.clone()).get("hil-teams-principal-map").cloned().unwrap_or_else(|| String::from(""))), (String::from("slack_team_id"), slack_team_id.clone()), (String::from("slack_principal_map_secret_id"), (secrets.clone()).get("hil-slack-principal-map").cloned().unwrap_or_else(|| String::from("")))]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn required_environment(mut environment: std::collections::BTreeMap<String, String>, mut name: String) -> Result<String, &'static str> {
    if environment.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn objects(mut value: String, mut label: String) -> Result<Vec<std::collections::BTreeMap<String, String>>, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn object(mut value: String, mut label: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if !(false) {
        return Err("label must be an object");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn string_mapping(mut value: String, mut label: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let result: std::collections::BTreeMap<String, String> = object(value.clone(), label.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn text(mut value: String, mut label: String) -> Result<String, &'static str> {
    if (!(true)) || (((value.clone()).is_empty()) || ((value.clone()) != (value.trim().to_string()))) {
        return Err("label must be a non-empty string");
    }
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn resource_id(mut value: String, mut label: String) -> Result<String, &'static str> {
    let result: String = text(value.clone(), label.clone()).unwrap_or_else(|_| String::new());
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn secret_id(mut value: String, mut label: String) -> Result<String, &'static str> {
    let result: String = text(value.clone(), label.clone()).unwrap_or_else(|_| String::new());
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn integer(mut value: String, mut label: String) -> Result<i64, &'static str> {
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn read_object(mut path: String, mut label: String) -> std::collections::BTreeMap<String, String> {
    object(String::new(), label.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn write_private(mut path: String, mut value: std::collections::BTreeMap<String, String>) {
    if path.is_empty() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn main() -> i64 {
    let recovered: std::collections::BTreeMap<String, String> = recover_operator_tfvars(read_object(String::new(), String::from("Operator ARM readback")), read_object(String::new(), String::from("platform binding"))).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let _ = write_private(String::new(), recovered.clone());
    0_i64
}

