pub const SCHEMA_VERSION: &str = "fdai.service-deployment-plan.v6";
pub const SHA256_PATTERN: &str = "[0-9a-f]{64}";
pub const COMMIT_PATTERN: &str = "[0-9a-f]{40}";
pub const DIGEST_IMAGE: &str = "[^\\s]+@sha256:[0-9a-f]{64}";
pub const PROBE_FIELDS: &[&str] = &["startup_probe", "liveness_probe", "readiness_probe"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PlanBundleError {
    pub message: String,
}

impl PlanBundleError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for PlanBundleError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PlanBundleError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn digest(mut path: String) -> String {
    if path.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn canonical(mut payload: std::collections::BTreeMap<String, String>) -> Vec<u8> {
    if payload.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn read_object(mut path: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn required(mut value: String, mut field: String) -> Result<String, &'static str> {
    if ((value.clone()).is_empty()) || (((value.clone()).contains("\n")) || ((value.clone()).contains("\r"))) {
        return Err("field must be non-empty and single-line");
    }
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resource_ids(mut value: String) -> Vec<String> {
    let found: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    (found.clone()).into_iter().collect::<Vec<String>>()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn containers(mut resource: std::collections::BTreeMap<String, String>, mut address: String) -> Result<std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>, &'static str> {
    let templates: Option<String> = (resource.clone()).get("template").cloned();
    let mut containers: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>> = std::collections::BTreeMap::<String, std::collections::BTreeMap<String, String>>::new();
    Ok(containers.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn planned_sidecar_contract(mut container: std::collections::BTreeMap<String, String>, mut name: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let image: Option<String> = (container.clone()).get("image").cloned();
    let mut probes: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>> = std::collections::BTreeMap::<String, std::collections::BTreeMap<String, String>>::new();
    Ok(std::collections::BTreeMap::from([(String::from("name"), name.clone()), (String::from("image_ref"), (image.clone()).unwrap_or_default()), (String::from("config_digest"), String::new()), (String::from("probe_digest"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn container_contract(mut resource: std::collections::BTreeMap<String, String>, mut address: String, mut service: String, mut image_ref: String) -> Result<(std::collections::BTreeMap<String, String>, Vec<std::collections::BTreeMap<String, String>>), &'static str> {
    let containers: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>> = containers(resource.clone(), address.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let primary_contract: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("name"), String::new()), (String::from("image_ref"), image_ref.clone()), (String::from("config_digest"), String::new())]);
    Ok((std::collections::BTreeMap::new(), Vec::new()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn target_context(mut payload: std::collections::BTreeMap<String, String>, mut allowed_address: String, mut service: String, mut subscription_id: String, mut image_ref: String, mut initial_cutover: bool, mut resource_side: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if !(matches!(resource_side.as_str(), "before" | "after")) {
        return Err("target context resource side must be before or after");
    }
    let changes: Option<String> = (payload.clone()).get("resource_changes").cloned();
    if !(true) {
        return Err("plan JSON resource_changes must be an array");
    }
    let service_name: String = required(String::new(), String::from("service name")).unwrap_or_else(|_| String::new());
    let resource_group: String = required(String::new(), String::from("service resource group")).unwrap_or_else(|_| String::new());
    let environment_id: String = required(String::new(), String::from("Container Apps environment id")).unwrap_or_else(|_| String::new());
    Ok(std::collections::BTreeMap::from([(String::from("service_resource_id"), String::new()), (String::from("service_name"), service_name.clone()), (String::from("resource_group"), resource_group.clone()), (String::from("component_tag"), String::new()), (String::from("container_app_environment_id"), (environment_id.clone()).to_lowercase()), (String::from("identity_resource_ids"), String::new()), (String::from("referenced_resource_ids"), String::new()), (String::from("image_ref"), image_ref.clone()), (String::from("primary_container"), String::new()), (String::from("sidecar_containers"), String::new()), (String::from("runtime_contract_digest"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn deployment_context(mut plan_json: String, mut service: String, mut environment: String, mut repository: String, mut commit_sha: String, mut image_ref: String, mut image_digest: String, mut tenant_id: String, mut subscription_id: String, mut backend_resource_group: String, mut backend_storage_account: String, mut backend_container: String, mut controls_commit_sha: String, mut resolved_models_digest: String, mut attestation_signer_workflow: String, mut initial_cutover: bool, mut database_host_binding: bool, mut degraded_recovery: bool, mut core_evidence_bindings_transition: bool, mut runtime_call_evidence_transition: bool, mut model_binding_transition: bool, mut operator_channel_edge_transition: String, mut document_channel_intake_transition: String, mut sharepoint_connector_transition: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let deployment_mode: String = deployment_mode(service.clone(), initial_cutover, database_host_binding, core_evidence_bindings_transition, runtime_call_evidence_transition, model_binding_transition, operator_channel_edge_transition.clone(), document_channel_intake_transition.clone(), sharepoint_connector_transition.clone()).unwrap_or_else(|_| String::new());
    if (degraded_recovery) && (((service.clone()) != (String::from("operator-service"))) || ((deployment_mode.clone()) != (String::from("database-host-binding")))) {
        return Err("degraded recovery is valid only for Operator database host binding");
    }
    let mut context: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("service"), service.clone()), (String::from("environment"), environment.clone()), (String::from("repository"), repository.clone()), (String::from("commit_sha"), commit_sha.clone()), (String::from("terraform_root"), String::new()), (String::from("tenant_id"), required(tenant_id.clone(), String::from("tenant id")).unwrap_or_else(|_| String::new())), (String::from("subscription_id"), required(subscription_id.clone(), String::from("subscription id")).unwrap_or_else(|_| String::new())), (String::from("backend"), String::new()), (String::from("target"), String::new()), (String::from("attestation"), String::new()), (String::from("trusted_controls"), String::new()), (String::from("deployment_mode"), deployment_mode.clone()), (String::from("degraded_recovery"), String::new())]);
    let plan_payload: std::collections::BTreeMap<String, String> = read_object(plan_json.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let edge_address: String = String::from("module.operator_service.module.channel_edge[0].azurerm_container_app.service");
    let edge_changes: Option<String> = (plan_payload.clone()).get("resource_changes").cloned();
    let intake_address: String = String::from("module.document_ingestion_api.module.channel_intake[0].azurerm_container_app.service");
    if (service.clone()) == (String::from("core-control-plane")) {
    } else if !(resolved_models_digest.clone()).is_empty() {
        return Err("resolved-models digest is valid only for the Core control plane");
    }
    Ok(context.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::too_many_arguments)]
pub fn deployment_mode(mut service: String, mut initial_cutover: bool, mut database_host_binding: bool, mut core_evidence_bindings_transition: bool, mut runtime_call_evidence_transition: bool, mut model_binding_transition: bool, mut operator_channel_edge_transition: String, mut document_channel_intake_transition: String, mut sharepoint_connector_transition: String) -> Result<String, &'static str> {
    if !(matches!(operator_channel_edge_transition.as_str(), "none" | "enable" | "disable")) {
        return Err("operator channel edge transition must be none enable or disable");
    }
    if ((operator_channel_edge_transition.clone()) != (String::from("none"))) && ((service.clone()) != (String::from("operator-service"))) {
        return Err("operator channel edge transition is valid only for operator-service");
    }
    if !(matches!(document_channel_intake_transition.as_str(), "none" | "enable" | "disable")) {
        return Err("document channel intake transition must be none enable or disable");
    }
    if ((document_channel_intake_transition.clone()) != (String::from("none"))) && ((service.clone()) != (String::from("document-ingestion-api"))) {
        return Err("document channel intake transition is valid only for document-ingestion-");
    }
    if !(matches!(sharepoint_connector_transition.as_str(), "none" | "enable" | "disable")) {
        return Err("SharePoint connector transition must be none enable or disable");
    }
    if ((sharepoint_connector_transition.clone()) != (String::from("none"))) && ((service.clone()) != (String::from("document-ingestion-api"))) {
        return Err("SharePoint connector transition is valid only for document-ingestion-api");
    }
    if ((sharepoint_connector_transition.clone()) != (String::from("none"))) && ((initial_cutover) || ((database_host_binding) || ((core_evidence_bindings_transition) || ((runtime_call_evidence_transition) || ((model_binding_transition) || (((operator_channel_edge_transition.clone()) != (String::from("none"))) || ((document_channel_intake_transition.clone()) != (String::from("none"))))))))) {
        return Err("SharePoint connector transition must be applied independently");
    }
    if (initial_cutover) && (((operator_channel_edge_transition.clone()) != (String::from("none"))) || ((document_channel_intake_transition.clone()) != (String::from("none")))) {
        return Err("initial cutover and operator channel edge transition are exclusive");
    }
    if (database_host_binding) && ((initial_cutover) || (((operator_channel_edge_transition.clone()) != (String::from("none"))) || ((document_channel_intake_transition.clone()) != (String::from("none"))))) {
        return Err("database host binding is exclusive with initial cutover and channel-edge");
    }
    if (model_binding_transition) && ((initial_cutover) || (((operator_channel_edge_transition.clone()) != (String::from("none"))) || ((document_channel_intake_transition.clone()) != (String::from("none"))))) {
        return Err("model binding transition is exclusive with initial cutover and channel-e");
    }
    if (core_evidence_bindings_transition) && ((service.clone()) != (String::from("core-control-plane"))) {
        return Err("core evidence binding transition is valid only for core-control-plane");
    }
    if (core_evidence_bindings_transition) && ((initial_cutover) || ((database_host_binding) || ((model_binding_transition) || (((operator_channel_edge_transition.clone()) != (String::from("none"))) || (((document_channel_intake_transition.clone()) != (String::from("none"))) || ((sharepoint_connector_transition.clone()) != (String::from("none")))))))) {
        return Err("core evidence binding transition must be applied independently");
    }
    if (database_host_binding) && (model_binding_transition) {
        return Ok(String::from("database-host-binding+model-binding"));
    }
    if database_host_binding {
        return Ok(String::from("database-host-binding"));
    }
    if model_binding_transition {
        return Ok(String::from("model-binding"));
    }
    if core_evidence_bindings_transition {
        return Ok(String::from("core-evidence-bindings"));
    }
    if runtime_call_evidence_transition {
        return Ok(String::from("runtime-call-evidence"));
    }
    if initial_cutover {
        return Ok(String::from("initial-cutover"));
    }
    if (operator_channel_edge_transition.clone()) != (String::from("none")) {
        return Ok(format!("operator-channel-edge-{}", operator_channel_edge_transition.clone()));
    }
    if (document_channel_intake_transition.clone()) != (String::from("none")) {
        return Ok(format!("document-channel-intake-{}", document_channel_intake_transition.clone()));
    }
    if (sharepoint_connector_transition.clone()) != (String::from("none")) {
        return Ok(format!("sharepoint-connector-{}", sharepoint_connector_transition.clone()));
    }
    Ok(String::from("standard"))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn create_bundle(mut plan: String, mut plan_json: String, mut context_path: String, mut metadata_path: String, mut service: String, mut environment: String, mut repository: String, mut commit_sha: String, mut image_ref: String, mut workflow_run_id: String, mut workflow_run_attempt: String, mut tenant_id: String, mut subscription_id: String, mut backend_resource_group: String, mut backend_storage_account: String, mut backend_container: String, mut controls_commit_sha: String, mut attestation_signer_workflow: String, mut now: String, mut resolved_models_digest: String, mut initial_cutover: bool, mut database_host_binding: bool, mut degraded_recovery: bool, mut core_evidence_bindings_transition: bool, mut runtime_call_evidence_transition: bool, mut model_binding_transition: bool, mut operator_channel_edge_transition: String, mut document_channel_intake_transition: String, mut sharepoint_connector_transition: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if !((!(workflow_run_id.clone()).is_empty() && (workflow_run_id.clone()).chars().all(|c| c.is_ascii_digit()))) {
        return Err("workflow_run_id must be numeric");
    }
    if (!((!(workflow_run_attempt.clone()).is_empty() && (workflow_run_attempt.clone()).chars().all(|c| c.is_ascii_digit())))) || (((workflow_run_attempt.clone()).trim().parse::<i64>().unwrap_or(0)) < (1_i64)) {
        return Err("workflow_run_attempt must be a positive integer");
    }
    let context: std::collections::BTreeMap<String, String> = deployment_context(plan_json.clone(), service.clone(), environment.clone(), repository.clone(), commit_sha.clone(), image_ref.clone(), String::new(), tenant_id.clone(), subscription_id.clone(), backend_resource_group.clone(), backend_storage_account.clone(), backend_container.clone(), controls_commit_sha.clone(), resolved_models_digest.clone(), attestation_signer_workflow.clone(), initial_cutover, database_host_binding, degraded_recovery, core_evidence_bindings_transition, runtime_call_evidence_transition, model_binding_transition, operator_channel_edge_transition.clone(), document_channel_intake_transition.clone(), sharepoint_connector_transition.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let context_digest: String = digest(context_path.clone());
    let metadata: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from(SCHEMA_VERSION)), (String::from("status"), String::from("ready")), (String::from("plan_id"), format!("{}-{}-{}-{}", service.clone(), environment.clone(), workflow_run_id.clone(), workflow_run_attempt.clone())), (String::from("service"), service.clone()), (String::from("environment"), environment.clone()), (String::from("commit_sha"), commit_sha.clone()), (String::from("backend_key"), String::new()), (String::from("terraform_root"), String::new()), (String::from("allowed_resource_address"), String::new()), (String::from("image_ref"), image_ref.clone()), (String::from("image_digest"), String::new()), (String::from("plan_digest"), digest(plan.clone())), (String::from("plan_json_digest"), digest(plan_json.clone())), (String::from("context_digest"), context_digest.clone()), (String::from("workflow_run_id"), workflow_run_id.clone()), (String::from("workflow_run_attempt"), workflow_run_attempt.clone()), (String::from("tenant_id"), tenant_id.clone()), (String::from("subscription_id"), subscription_id.clone()), (String::from("backend_resource_group"), backend_resource_group.clone()), (String::from("backend_storage_account"), backend_storage_account.clone()), (String::from("backend_container"), backend_container.clone()), (String::from("controls_commit_sha"), controls_commit_sha.clone()), (String::from("resolved_models_digest"), resolved_models_digest.clone()), (String::from("attestation_signer_workflow"), attestation_signer_workflow.clone()), (String::from("degraded_recovery"), String::new()), (String::from("deployment_mode"), deployment_mode(service.clone(), initial_cutover, database_host_binding, core_evidence_bindings_transition, runtime_call_evidence_transition, model_binding_transition, operator_channel_edge_transition.clone(), document_channel_intake_transition.clone(), sharepoint_connector_transition.clone()).unwrap_or_else(|_| String::new())), (String::from("created_at"), String::new()), (String::from("expires_at"), String::new())]);
    Ok(metadata.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn verify_bundle(mut plan: String, mut plan_json: String, mut context_path: String, mut metadata_path: String, mut service: String, mut environment: String, mut repository: String, mut commit_sha: String, mut image_ref: String, mut plan_digest: String, mut context_digest: String, mut plan_run_id: String, mut workflow_run_attempt: String, mut tenant_id: String, mut subscription_id: String, mut backend_resource_group: String, mut backend_storage_account: String, mut backend_container: String, mut controls_commit_sha: String, mut attestation_signer_workflow: String, mut now: String, mut resolved_models_digest: String, mut initial_cutover: bool, mut database_host_binding: bool, mut degraded_recovery: bool, mut core_evidence_bindings_transition: bool, mut runtime_call_evidence_transition: bool, mut model_binding_transition: bool, mut operator_channel_edge_transition: String, mut document_channel_intake_transition: String, mut sharepoint_connector_transition: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if !((!(plan_run_id.clone()).is_empty() && (plan_run_id.clone()).chars().all(|c| c.is_ascii_digit()))) {
        return Err("plan_run_id must be numeric");
    }
    let metadata: std::collections::BTreeMap<String, String> = read_object(metadata_path.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let expected: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from(SCHEMA_VERSION)), (String::from("status"), String::from("ready")), (String::from("plan_id"), format!("{}-{}-{}-{}", service.clone(), environment.clone(), plan_run_id.clone(), workflow_run_attempt.clone())), (String::from("service"), service.clone()), (String::from("environment"), environment.clone()), (String::from("commit_sha"), commit_sha.clone()), (String::from("backend_key"), String::new()), (String::from("terraform_root"), String::new()), (String::from("allowed_resource_address"), String::new()), (String::from("image_ref"), image_ref.clone()), (String::from("image_digest"), String::new()), (String::from("plan_digest"), plan_digest.clone()), (String::from("context_digest"), context_digest.clone()), (String::from("workflow_run_id"), plan_run_id.clone()), (String::from("workflow_run_attempt"), workflow_run_attempt.clone()), (String::from("tenant_id"), tenant_id.clone()), (String::from("subscription_id"), subscription_id.clone()), (String::from("backend_resource_group"), backend_resource_group.clone()), (String::from("backend_storage_account"), backend_storage_account.clone()), (String::from("backend_container"), backend_container.clone()), (String::from("controls_commit_sha"), controls_commit_sha.clone()), (String::from("resolved_models_digest"), resolved_models_digest.clone()), (String::from("attestation_signer_workflow"), attestation_signer_workflow.clone()), (String::from("degraded_recovery"), String::new()), (String::from("deployment_mode"), deployment_mode(service.clone(), initial_cutover, database_host_binding, core_evidence_bindings_transition, runtime_call_evidence_transition, model_binding_transition, operator_channel_edge_transition.clone(), document_channel_intake_transition.clone(), sharepoint_connector_transition.clone()).unwrap_or_else(|_| String::new()))]);
    for (key, value) in expected.clone() {
        if ((metadata.clone()).get(key.as_str()).cloned()) != Some(value.clone()) {
            return Err("plan metadata key does not match exact apply input");
        }
    }
    if (digest(plan.clone())) != (plan_digest.clone()) {
        return Err("binary plan digest does not match exact apply input");
    }
    if (digest(context_path.clone())) != (context_digest.clone()) {
        return Err("context digest does not match exact apply input");
    }
    let context: std::collections::BTreeMap<String, String> = read_object(context_path.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let expected_context: std::collections::BTreeMap<String, String> = deployment_context(plan_json.clone(), service.clone(), environment.clone(), repository.clone(), commit_sha.clone(), image_ref.clone(), String::new(), tenant_id.clone(), subscription_id.clone(), backend_resource_group.clone(), backend_storage_account.clone(), backend_container.clone(), controls_commit_sha.clone(), resolved_models_digest.clone(), attestation_signer_workflow.clone(), initial_cutover, database_host_binding, degraded_recovery, core_evidence_bindings_transition, runtime_call_evidence_transition, model_binding_transition, operator_channel_edge_transition.clone(), document_channel_intake_transition.clone(), sharepoint_connector_transition.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    Ok(metadata.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn common(mut parser: String) {
    if parser.is_empty() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn main() -> i64 {
    let _ = common(String::new());
    let _ = common(String::new());
    let common: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("plan"), String::new()), (String::from("plan_json"), String::new()), (String::from("context_path"), String::new()), (String::from("metadata_path"), String::new()), (String::from("service"), String::new()), (String::from("environment"), String::new()), (String::from("repository"), String::new()), (String::from("commit_sha"), String::new()), (String::from("image_ref"), String::new()), (String::from("workflow_run_attempt"), String::new()), (String::from("tenant_id"), String::new()), (String::from("subscription_id"), String::new()), (String::from("backend_resource_group"), String::new()), (String::from("backend_storage_account"), String::new()), (String::from("backend_container"), String::new()), (String::from("controls_commit_sha"), String::new()), (String::from("resolved_models_digest"), String::new()), (String::from("attestation_signer_workflow"), String::new()), (String::from("initial_cutover"), String::new()), (String::from("database_host_binding"), String::new()), (String::from("degraded_recovery"), String::new()), (String::from("core_evidence_bindings_transition"), String::new()), (String::from("runtime_call_evidence_transition"), String::new()), (String::from("model_binding_transition"), String::new()), (String::from("operator_channel_edge_transition"), String::new()), (String::from("document_channel_intake_transition"), String::new()), (String::from("sharepoint_connector_transition"), String::new())]);
    0_i64
}

