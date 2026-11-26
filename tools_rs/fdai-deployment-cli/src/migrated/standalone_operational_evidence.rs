pub const OPERATIONAL_EVIDENCE_PORT: i64 = 8791;

pub const GUID: &str = "[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}";
pub const OPERATIONAL_EVIDENCE_READINESS_PATH: &str = "/v1/operational-evidence/readiness";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn bind_service_database_role(mut service: String, mut environment: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn aks_workload(mut component: String, mut refs: std::collections::BTreeMap<String, String>, mut identity: std::collections::BTreeMap<String, String>, mut environment: std::collections::BTreeMap<String, String>, mut secret_environment: std::collections::BTreeMap<String, String>, mut readiness_path: String, mut liveness_path: String, mut external: bool, mut service_port: Option<i64>, mut fs_group: Option<i64>, mut additional_identities: Option<std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>>, mut sidecars: Option<std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let image_names: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("core"), String::from("core-control-plane")), (String::from("operator"), String::from("operator-service")), (String::from("executor"), String::from("isolated-executor")), (String::from("ingestion"), String::from("document-ingestion-api")), (String::from("worker"), String::from("document-processing-worker"))]);
    let image_name: Option<String> = (image_names.clone()).get(component.as_str()).cloned();
    let mut runtime_environment: std::collections::BTreeMap<String, String> = bind_service_database_role((image_name.clone()).unwrap_or_default(), environment.clone());
    runtime_environment.insert(String::from("FDAI_EXECUTION_VENUE"), String::from("deployed"));
    Ok(std::collections::BTreeMap::from([(String::from("component"), component.clone()), (String::from("image"), String::new()), (String::from("identity_resource_id"), String::new()), (String::from("identity_client_id"), String::new()), (String::from("additional_identities"), String::new()), (String::from("command"), String::new()), (String::from("args"), String::new()), (String::from("replicas"), String::new()), (String::from("max_replicas"), String::new()), (String::from("cpu"), String::new()), (String::from("memory"), String::new()), (String::from("port"), String::new()), (String::from("service_port"), String::new()), (String::from("external"), String::new()), (String::from("readiness_path"), readiness_path.clone()), (String::from("liveness_path"), liveness_path.clone()), (String::from("fs_group"), String::new()), (String::from("environment"), String::new()), (String::from("secret_environment"), String::new()), (String::from("sidecars"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn aks_operational_evidence_verifier_workload(mut refs: std::collections::BTreeMap<String, String>, mut verifier_identity: String, mut core_identity: std::collections::BTreeMap<String, String>, mut executor_identity: String, mut deploy_runner_principal: String, mut application_values: std::collections::BTreeMap<String, String>, mut postgres_fqdn: String, mut postgres_database: String) -> Result<Option<std::collections::BTreeMap<String, String>>, &'static str> {
    let binding: Option<String> = (application_values.clone()).get("operational_evidence_verifier").cloned();
    let Some(mut binding) = binding.clone() else { return Ok(None); };
    if !(false) {
        return Err("operational evidence verifier identity is unavailable");
    }
    let verifier: std::collections::BTreeMap<String, String> = identity_binding(std::collections::BTreeMap::new(), String::from("operational evidence verifier identity")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let core: std::collections::BTreeMap<String, String> = identity_binding(core_identity.clone(), String::from("Core runtime identity")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    if false {
    } else {
        let mut executor_principal: String = anchor_principal(String::new(), String::from("anchor:isolated-executor")).unwrap_or_else(|_| String::new());
    }
    let json_fields: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("anchors_json"), String::from("FDAI_OPERATIONAL_EVIDENCE_ANCHORS_JSON")), (String::from("caller_token_jwks_json"), String::from("FDAI_OPERATIONAL_EVIDENCE_CALLER_TOKEN_JWKS_JSON")), (String::from("role_readback_scopes_json"), String::from("FDAI_OPERATIONAL_EVIDENCE_ROLE_READBACK_SCOPES_JSON")), (String::from("allowed_role_scopes_json"), String::from("FDAI_OPERATIONAL_EVIDENCE_ALLOWED_ROLE_SCOPES_JSON")), (String::from("vertical_executor_principals_json"), String::from("FDAI_OPERATIONAL_EVIDENCE_VERTICAL_EXECUTOR_PRINCIPALS_JSON")), (String::from("writer_members_json"), String::from("FDAI_OPERATIONAL_EVIDENCE_WRITER_MEMBERS_JSON"))]);
    let optional_fields: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("grant_registry_json"), String::from("FDAI_OPERATIONAL_EVIDENCE_GRANT_REGISTRY_JSON")), (String::from("observation_metric_workspace_id"), String::from("FDAI_OPERATIONAL_EVIDENCE_OBSERVATION_METRIC_WORKSPACE_ID")), (String::from("observation_metric_queries_json"), String::from("FDAI_OPERATIONAL_EVIDENCE_OBSERVATION_METRIC_QUERIES_JSON")), (String::from("observation_scope_rows_json"), String::from("FDAI_OPERATIONAL_EVIDENCE_OBSERVATION_SCOPE_ROWS_JSON")), (String::from("forecast_history_sources_json"), String::from("FDAI_FORECAST_HISTORY_SOURCES_JSON"))]);
    let mut environment: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("AZURE_CLIENT_ID"), String::new()), (String::from("FDAI_MI_CLIENT_ID"), String::new()), (String::from("POSTGRES_HOST"), postgres_fqdn.clone()), (String::from("POSTGRES_DATABASE"), postgres_database.clone()), (String::from("FDAI_DATABASE_ROLE"), String::from("fdai_operational_evidence_verifier")), (String::from("PGOPTIONS"), String::from("-c role=fdai_operational_evidence_verifier")), (String::from("RUNTIME_ENV"), String::new()), (String::from("FDAI_OPERATIONAL_EVIDENCE_ENABLED"), String::from("1")), (String::from("FDAI_OPERATIONAL_EVIDENCE_TRUST_REGISTRY_PATH"), optional_text(std::collections::BTreeMap::new(), String::from("trust_registry_path"), String::from("config/operational-evidence-trust-registry.json")).unwrap_or_else(|_| String::new())), (String::from("FDAI_OPERATIONAL_EVIDENCE_TRUST_REGISTRY_PIN"), required_text(std::collections::BTreeMap::new(), String::from("trust_registry_pin")).unwrap_or_else(|_| String::new())), (String::from("FDAI_OPERATIONAL_EVIDENCE_GRANT_REGISTRY_PATH"), required_text(std::collections::BTreeMap::new(), String::from("grant_registry_path")).unwrap_or_else(|_| String::new())), (String::from("FDAI_OPERATIONAL_EVIDENCE_GRANT_REGISTRY_PIN"), required_text(std::collections::BTreeMap::new(), String::from("grant_registry_pin")).unwrap_or_else(|_| String::new())), (String::from("FDAI_OPERATIONAL_EVIDENCE_VERIFIER_URL"), format!("http://127.0.0.1:{}", OPERATIONAL_EVIDENCE_PORT)), (String::from("FDAI_OPERATIONAL_EVIDENCE_READER_ROLE"), String::from("fdai_core")), (String::from("FDAI_OPERATIONAL_EVIDENCE_CORE_EXECUTOR_PRINCIPAL_ID"), String::new()), (String::from("FDAI_OPERATIONAL_EVIDENCE_ISOLATED_EXECUTOR_PRINCIPAL_ID"), String::new()), (String::from("FDAI_OPERATIONAL_EVIDENCE_DEV_GATEWAY_EXECUTOR_PRINCIPAL_ID"), required_text(std::collections::BTreeMap::new(), String::from("dev_gateway_executor_principal_id")).unwrap_or_else(|_| String::new())), (String::from("FDAI_OPERATIONAL_EVIDENCE_DEPLOY_RUNNER_PRINCIPAL_ID"), deploy_runner_principal.clone()), (String::from("FDAI_OPERATIONAL_EVIDENCE_CALLER_TOKEN_ISSUER"), required_text(std::collections::BTreeMap::new(), String::from("caller_token_issuer")).unwrap_or_else(|_| String::new())), (String::from("FDAI_OPERATIONAL_EVIDENCE_CALLER_TOKEN_AUDIENCE"), required_text(std::collections::BTreeMap::new(), String::from("caller_token_audience")).unwrap_or_else(|_| String::new()))]);
    for (key, env_name) in json_fields.clone() {
        environment.insert(env_name.clone(), required_json_text(std::collections::BTreeMap::new(), key.clone()).unwrap_or_else(|_| String::new()));
    }
    for (key, env_name) in optional_fields.clone() {
        if (binding.clone()).contains(key.as_str()) {
            environment.insert(env_name.clone(), if (key.clone()) == (String::from("observation_metric_workspace_id")) { required_text(std::collections::BTreeMap::new(), key.clone()).unwrap_or_else(|_| String::new()) } else { required_json_text(std::collections::BTreeMap::new(), key.clone()).unwrap_or_else(|_| String::new()) });
        }
    }
    let image: Option<String> = (refs.clone()).get("core-control-plane").cloned();
    if !(true) {
        return Err("AKS operational evidence verifier image is unavailable");
    }
    Ok(Some(std::collections::BTreeMap::from([(String::from("component"), String::from("operational-evidence-verifier")), (String::from("image"), (image.clone()).unwrap_or_default()), (String::from("identity_resource_id"), String::new()), (String::from("identity_client_id"), String::new()), (String::from("additional_identities"), String::new()), (String::from("command"), String::new()), (String::from("args"), String::new()), (String::from("replicas"), String::new()), (String::from("max_replicas"), String::new()), (String::from("cpu"), String::from("500m")), (String::from("memory"), String::from("1Gi")), (String::from("port"), String::new()), (String::from("service_port"), String::new()), (String::from("external"), String::new()), (String::from("readiness_path"), String::from(OPERATIONAL_EVIDENCE_READINESS_PATH)), (String::from("liveness_path"), String::from(OPERATIONAL_EVIDENCE_READINESS_PATH)), (String::from("fs_group"), String::new()), (String::from("environment"), String::new()), (String::from("secret_environment"), String::new()), (String::from("sidecars"), String::new())])))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn add_aks_operational_evidence_verifier_workload(mut workloads: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>, mut refs: std::collections::BTreeMap<String, String>, mut identities: std::collections::BTreeMap<String, String>, mut substrate_outputs: std::collections::BTreeMap<String, String>, mut context: std::collections::BTreeMap<String, String>, mut application_values: std::collections::BTreeMap<String, String>) {
    if ((application_values.clone()).get("operational_evidence_verifier").cloned()).is_none() {
        return;
    }
    let verifier_workload: Option<std::collections::BTreeMap<String, String>> = aks_operational_evidence_verifier_workload(refs.clone(), String::new(), mapping(String::new(), String::from("Core runtime identity")).unwrap_or_else(|_| std::collections::BTreeMap::new()), String::new(), required_text(context.clone(), String::from("principal_id")).unwrap_or_else(|_| String::new()), application_values.clone(), required_text(substrate_outputs.clone(), String::from("postgres_fqdn")).unwrap_or_else(|_| String::new()), required_text(substrate_outputs.clone(), String::from("postgres_database")).unwrap_or_else(|_| String::new())).unwrap_or_else(|_| None);
    if let Some(mut verifier_workload) = verifier_workload.clone() {
        workloads.insert(String::from("operational-evidence-verifier"), verifier_workload.clone());
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn runtime_principal_ids_with_operational_evidence_verifier(mut identities: std::collections::BTreeMap<String, String>, mut names: Vec<String>) -> std::collections::BTreeSet<String> {
    let verifier_identity: Option<String> = (identities.clone()).get("operational_evidence_verifier").cloned();
    std::collections::BTreeSet::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn mapping(mut value: String, mut label: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn identity_binding(mut value: std::collections::BTreeMap<String, String>, mut label: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("resource_id"), required_text(value.clone(), String::from("resource_id")).unwrap_or_else(|_| String::new())), (String::from("client_id"), required_text(value.clone(), String::from("client_id")).unwrap_or_else(|_| String::new())), (String::from("principal_id"), required_text(value.clone(), String::from("principal_id")).unwrap_or_else(|_| String::new()))]);
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn required_text(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<String, &'static str> {
    let item: Option<String> = (value.clone()).get(key.as_str()).cloned();
    if (!(true)) || ((((item.clone()).unwrap_or_default()).trim().to_string()).is_empty()) {
        return Err("key is required");
    }
    Ok(((item.clone()).unwrap_or_default()).trim().to_string())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn optional_text(mut value: std::collections::BTreeMap<String, String>, mut key: String, mut default: String) -> Result<String, &'static str> {
    let item: String = (value.clone()).get(key.as_str()).cloned().unwrap_or_else(|| default.clone());
    if (!(true)) || (((item.clone()).trim().to_string()).is_empty()) {
        return Err("key is required");
    }
    Ok((item.clone()).trim().to_string())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn required_json_text(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<String, &'static str> {
    let item: String = required_text(value.clone(), key.clone()).unwrap_or_else(|_| String::new());
    Ok(item.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn anchor_principal(mut anchors_json: String, mut anchor_id: String) -> Result<String, &'static str> {
    Err("operational evidence verifier requires the isolated executor anchor")
}

