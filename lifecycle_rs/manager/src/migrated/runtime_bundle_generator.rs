use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct PreExistingReferences {
    pub service_accounts: Vec<String>,
    pub secret_provider_classes: Vec<String>,
    pub config_maps: Vec<String>,
    pub secrets: Vec<String>,
    #[allow(clippy::type_complexity)]
    pub config_map_data: BTreeMap<String, BTreeMap<String, String>>,
    #[allow(clippy::type_complexity)]
    pub secret_bindings: BTreeMap<String, BTreeMap<String, String>>,
    #[allow(clippy::type_complexity)]
    pub identity_bindings: BTreeMap<String, BTreeMap<String, String>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct GeneratedRuntimeTopology {
    pub bundle: String,
    pub component_images: BTreeMap<String, String>,
    pub native_scope: String,
    pub prerequisites: Box<PreExistingReferences>,
}

pub const IMAGE: &str = "^[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+@sha256:[0-9a-f]{64}\\Z";
pub const MEMORY_GI: &str = "^([1-9][0-9]*)Gi\\Z";
pub const MEMORY_MI: &str = "^([1-9][0-9]*)Mi\\Z";
pub const CPU_CORES: &str = "^([1-9][0-9]*)\\Z";
pub const CPU_MILLIS: &str = "^([1-9][0-9]*)m\\Z";
pub const ENV_NAME: &str = "^[A-Za-z_][A-Za-z0-9_]{0,127}\\Z";
pub const KV_SECRET_NAME: &str = "^[A-Za-z0-9-]{1,127}\\Z";
pub const KEBAB_ID: &str = "^[a-z0-9]+(?:-[a-z0-9]+)*\\Z";
pub const STENCIL_ID: &str = "^[a-z][a-z0-9-]{0,62}\\Z";
pub const LOCKED_STENCIL_PANELS: &[&str] = &["audit", "dashboard", "settings-general"];
pub const CANARY_UID_FIELD: &str = "metadata.labels['batch.kubernetes.io/controller-uid']";
impl GeneratedRuntimeTopology {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        core::hint::black_box(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn require_str(mut mapping: std::collections::BTreeMap<String, String>, mut key: String, mut label: String) -> Result<String, &'static str> {
    let value: Option<String> = (mapping.clone()).get(key.as_str()).cloned();
    if (!(true)) || ((((value.clone()).unwrap_or_default()).trim().to_string()).is_empty()) {
        return Err("label.key must be a non-empty string.");
    }
    Ok((value.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn require_int(mut mapping: std::collections::BTreeMap<String, String>, mut key: String, mut label: String, mut default: Option<i64>, mut minimum: i64, mut maximum: i64) -> Result<i64, &'static str> {
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_mapping(mut mapping: std::collections::BTreeMap<String, String>, mut key: String, mut label: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let value: Option<String> = (mapping.clone()).get(key.as_str()).cloned();
    if !(true) {
        return Err("label.key must be a mapping.");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn normalize_cpu(mut value: String) -> Result<String, &'static str> {
    Err("Unsupported CPU quantity: value")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn normalize_memory(mut value: String) -> Result<String, &'static str> {
    Err("Unsupported memory quantity: value")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn validate_image(mut image: String, mut label: String) -> Result<String, &'static str> {
    Ok(image.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn record_component_image(mut component_images: std::collections::BTreeMap<String, String>, mut component: String, mut image: String) -> Result<(), &'static str> {
    let existing: Option<String> = (component_images.clone()).get(component.as_str()).cloned();
    if (existing.is_some()) && ((existing.clone()) != Some(image.clone())) {
        return Err("Component component has conflicting image digests.");
    }
    component_images.insert(component.clone(), image.clone());
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_and_record_identity(mut spec: std::collections::BTreeMap<String, String>, mut sa_name: String, mut label: String, mut identity_bindings: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>) -> Result<(), &'static str> {
    let client_id: String = require_str(spec.clone(), String::from("identity_client_id"), label.clone()).unwrap_or_else(|_| String::new());
    let resource_id: String = require_str(spec.clone(), String::from("identity_resource_id"), label.clone()).unwrap_or_else(|_| String::new());
    let mut extra: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>> = std::collections::BTreeMap::<String, std::collections::BTreeMap<String, String>>::new();
    identity_bindings.insert(sa_name.clone(), std::collections::BTreeMap::from([(String::from("client_id"), client_id.clone()), (String::from("resource_id"), resource_id.clone())]));
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_env_contracts(mut label: String, mut component: String, mut environment: std::collections::BTreeMap<String, String>, mut secret_environment: std::collections::BTreeMap<String, String>, mut field_environment: std::collections::BTreeMap<String, String>) -> Result<(std::collections::BTreeMap<String, String>, std::collections::BTreeMap<String, String>, std::collections::BTreeMap<String, String>), &'static str> {
    let mut env_out: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    let mut sec_out: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    let mut field_out: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok((env_out.clone(), sec_out.clone(), field_out.clone()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn build_env_references(mut secret_ref_name: String, mut secret_environment: std::collections::BTreeMap<String, String>, mut field_environment: Option<std::collections::BTreeMap<String, String>>) -> Vec<std::collections::BTreeMap<String, String>> {
    if secret_ref_name.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn build_base_volumes(mut ref_name: String, mut tmp_size: String, mut has_secrets: bool, mut identity_bridge_enabled: bool, mut identity_bridge_config_map: Option<String>, mut identity_bridge_size_limit: Option<String>, mut config_maps: std::collections::BTreeSet<String>, mut secret_provider_classes: std::collections::BTreeSet<String>, mut secrets: std::collections::BTreeSet<String>) -> Result<(Vec<std::collections::BTreeMap<String, String>>, Vec<std::collections::BTreeMap<String, String>>), &'static str> {
    let mut volumes: Vec<std::collections::BTreeMap<String, String>> = vec![std::collections::BTreeMap::from([(String::from("name"), String::from("tmp")), (String::from("emptyDir"), String::new())])];
    let mut mounts: Vec<std::collections::BTreeMap<String, String>> = vec![std::collections::BTreeMap::from([(String::from("name"), String::from("tmp")), (String::from("mountPath"), String::from("/tmp"))])];
    if identity_bridge_enabled {
        let mut identity_bridge_config_map: String = match identity_bridge_config_map.clone() { Some(_v) if !_v.is_empty() => _v, _ => return Err("ref_name requires identity_bridge_config_map.") };
        config_maps.insert(identity_bridge_config_map.clone());
        volumes.push(std::collections::BTreeMap::from([(String::from("name"), String::from("identity-bridge")), (String::from("configMap"), String::new())]));
        mounts.push(std::collections::BTreeMap::from([(String::from("name"), String::from("identity-bridge")), (String::from("mountPath"), String::from("/opt/fdai-compat")), (String::from("readOnly"), String::new())]));
        if let Some(mut identity_bridge_size_limit) = identity_bridge_size_limit.clone() {
            volumes.push(std::collections::BTreeMap::from([(String::from("name"), String::from("runtime-state")), (String::from("emptyDir"), String::new())]));
            mounts.push(std::collections::BTreeMap::from([(String::from("name"), String::from("runtime-state")), (String::from("mountPath"), String::from("/app/.fdai")), (String::from("readOnly"), String::new())]));
        }
    }
    if has_secrets {
        secret_provider_classes.insert(ref_name.clone());
        secrets.insert(ref_name.clone());
        volumes.push(std::collections::BTreeMap::from([(String::from("name"), String::from("secrets")), (String::from("csi"), String::new())]));
        mounts.push(std::collections::BTreeMap::from([(String::from("name"), String::from("secrets")), (String::from("mountPath"), String::from("/mnt/secrets-store")), (String::from("readOnly"), String::new())]));
    }
    Ok((volumes.clone(), mounts.clone()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn build_sidecars(mut name: String, mut sidecars: std::collections::BTreeMap<String, String>, mut component_images: std::collections::BTreeMap<String, String>, mut volumes: Vec<std::collections::BTreeMap<String, String>>) -> Result<(Vec<std::collections::BTreeMap<String, String>>, Vec<std::collections::BTreeMap<String, String>>), &'static str> {
    let mut containers: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    let mut init_containers: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    Ok((containers.clone(), init_containers.clone()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn build_deployment_and_service(mut name: String, mut workload: std::collections::BTreeMap<String, String>, mut entity_id: String, mut namespace: String, mut canary_scheduled: bool, mut identity_bridge_config_map: Option<String>, mut identity_bridge_size_limit: String, mut component_images: std::collections::BTreeMap<String, String>, mut service_accounts: std::collections::BTreeSet<String>, mut secret_provider_classes: std::collections::BTreeSet<String>, mut config_maps: std::collections::BTreeSet<String>, mut secrets: std::collections::BTreeSet<String>, mut config_map_data: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>, mut secret_bindings: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>, mut identity_bindings: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>) -> Result<(String, String, String), &'static str> {
    let label: String = format!("workload {}", name.clone());
    let _ = record_component_image(component_images.clone(), name.clone(), validate_image(String::new(), label.clone()).unwrap_or_else(|_| String::new())).unwrap_or_else(|_| ());
    let _ = validate_and_record_identity(workload.clone(), name.clone(), label.clone(), identity_bindings.clone()).unwrap_or_else(|_| ());
    let replicas: i64 = require_int(workload.clone(), String::from("replicas"), label.clone(), Some(2_i64), 1_i64, 3_i64).unwrap_or_else(|_| 0_i64);
    let max_replicas: i64 = require_int(workload.clone(), String::from("max_replicas"), label.clone(), Some(replicas), replicas, 10_i64).unwrap_or_else(|_| 0_i64);
    let port: i64 = require_int(workload.clone(), String::from("port"), label.clone(), Some(8000_i64), 1_i64, 65535_i64).unwrap_or_else(|_| 0_i64);
    let raw_svc_port: Option<String> = (workload.clone()).get("service_port").cloned();
    let service_port: i64 = if raw_svc_port.is_none() { port } else { require_int(workload.clone(), String::from("service_port"), label.clone(), None, 1_i64, 65535_i64).unwrap_or_else(|_| 0_i64) };
    let mut raw_env: std::collections::BTreeMap<String, String> = if (workload.clone()).contains_key("environment") { require_mapping(workload.clone(), String::from("environment"), label.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new()) } else { std::collections::BTreeMap::<String, String>::new() };
    let raw_sec: std::collections::BTreeMap<String, String> = if (workload.clone()).contains_key("secret_environment") { require_mapping(workload.clone(), String::from("secret_environment"), label.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new()) } else { std::collections::BTreeMap::<String, String>::new() };
    service_accounts.insert(name.clone());
    let env_cm_name: String = format!("{}-env", name.clone());
    config_maps.insert(env_cm_name.clone());
    let cpu: String = normalize_cpu((workload.clone()).get("cpu").cloned().unwrap_or_else(|| String::from("500m"))).unwrap_or_else(|_| String::new());
    let memory: String = normalize_memory((workload.clone()).get("memory").cloned().unwrap_or_else(|| String::from("1Gi"))).unwrap_or_else(|_| String::new());
    let readiness_path: String = require_str(workload.clone(), String::from("readiness_path"), label.clone()).unwrap_or_else(|_| String::new());
    let liveness_path: String = (workload.clone()).get("liveness_path").cloned().unwrap_or_else(|| readiness_path.clone());
    let mut primary: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("name"), name.clone()), (String::from("image_component"), name.clone()), (String::from("imagePullPolicy"), String::from("Always")), (String::from("resources"), String::new()), (String::from("securityContext"), String::new()), (String::from("ports"), String::new()), (String::from("readinessProbe"), String::new()), (String::from("livenessProbe"), String::new()), (String::from("envFrom"), String::new()), (String::from("volumeMounts"), String::new())]);
    let mut pod_sec: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("runAsNonRoot"), String::new()), (String::from("seccompProfile"), String::new())]);
    let pod_spec: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("serviceAccountName"), name.clone()), (String::from("automountServiceAccountToken"), String::new()), (String::from("terminationGracePeriodSeconds"), String::new()), (String::from("nodeSelector"), String::new()), (String::from("securityContext"), String::new()), (String::from("containers"), String::new()), (String::from("volumes"), String::new())]);
    Ok((String::new(), String::new(), String::new()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn build_cron_job(mut name: String, mut job: std::collections::BTreeMap<String, String>, mut entity_id: String, mut image_component: String, mut identity_bridge_config_map: Option<String>, mut component_images: std::collections::BTreeMap<String, String>, mut service_accounts: std::collections::BTreeSet<String>, mut secret_provider_classes: std::collections::BTreeSet<String>, mut config_maps: std::collections::BTreeSet<String>, mut secrets: std::collections::BTreeSet<String>, mut config_map_data: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>, mut secret_bindings: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>, mut identity_bindings: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>) -> Result<String, &'static str> {
    let label: String = format!("scheduled job {}", name.clone());
    let _ = record_component_image(component_images.clone(), image_component.clone(), validate_image(String::new(), label.clone()).unwrap_or_else(|_| String::new())).unwrap_or_else(|_| ());
    let sa_name: String = format!("{}-job", name.clone());
    let _ = validate_and_record_identity(job.clone(), sa_name.clone(), label.clone(), identity_bindings.clone()).unwrap_or_else(|_| ());
    service_accounts.insert(sa_name.clone());
    let env_cm_name: String = format!("{}-job-env", name.clone());
    let component: String = (job.clone()).get("component").cloned().unwrap_or_else(|| name.clone());
    config_maps.insert(env_cm_name.clone());
    let cpu: String = normalize_cpu((job.clone()).get("cpu").cloned().unwrap_or_else(|| String::from("500m"))).unwrap_or_else(|_| String::new());
    let memory: String = normalize_memory((job.clone()).get("memory").cloned().unwrap_or_else(|| String::from("1Gi"))).unwrap_or_else(|_| String::new());
    let mut container: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("name"), name.clone()), (String::from("image_component"), image_component.clone()), (String::from("command"), String::new()), (String::from("resources"), String::new()), (String::from("securityContext"), String::new()), (String::from("envFrom"), String::new()), (String::from("volumeMounts"), String::new())]);
    let env_refs: Vec<std::collections::BTreeMap<String, String>> = build_env_references(sa_name.clone(), std::collections::BTreeMap::new(), None);
    let deadline_seconds: i64 = require_int(job.clone(), String::from("deadline_seconds"), label.clone(), Some(240_i64), 1_i64, 900_i64).unwrap_or_else(|_| 0_i64);
    let job_labels: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("app.kubernetes.io/name"), name.clone()), (String::from("app.kubernetes.io/component"), component.clone()), (String::from("fdai.io/runtime"), String::from("aks"))]);
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn generate_fdai_runtime_bundle(mut workloads: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>, mut scheduled_jobs: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>, mut installation_id: String, mut entity_id: String, mut product: String, mut namespace: String, mut scheduled_job_image_component: String, mut identity_bridge_config_map: Option<String>, mut identity_bridge_size_limit: String, mut enabled_workloads: Option<std::collections::BTreeSet<String>>, mut enabled_scheduled_jobs: Option<std::collections::BTreeSet<String>>, mut stencil_id: Option<String>, mut enabled_panel_ids: Option<std::collections::BTreeSet<String>>, mut enabled_loops: Option<std::collections::BTreeSet<String>>, mut catalog_freshness: Option<std::collections::BTreeMap<String, String>>) -> Result<GeneratedRuntimeTopology, &'static str> {
    if let Some(mut enabled_loops) = enabled_loops.clone() {
        if ((enabled_loops.clone()).contains("remediation-execution")) && (!((workloads.clone()).contains_key("isolated-executor"))) {
            return Err("Stencil loop remediation-execution requires workload isolated-executor.");
        }
        if ((enabled_loops.clone()).contains("cost-governance")) && (!((scheduled_jobs.clone()).contains_key("cost-collector"))) {
            return Err("Stencil loop cost-governance requires scheduled job cost-collector.");
        }
    }
    if (workloads.clone()).is_empty() {
        return Err("At least one AKS workload is required.");
    }
    let mut objects: Vec<String> = Vec::<String>::new();
    let component_images: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    let mut service_accounts: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let secret_provider_classes: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let config_maps: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let secrets: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let mut config_map_data: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>> = std::collections::BTreeMap::<String, std::collections::BTreeMap<String, String>>::new();
    let secret_bindings: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>> = std::collections::BTreeMap::<String, std::collections::BTreeMap<String, String>>::new();
    let identity_bindings: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>> = std::collections::BTreeMap::<String, std::collections::BTreeMap<String, String>>::new();
    let canary_scheduled: bool = (scheduled_jobs.clone()).contains_key("canary");
    if (stencil_id.is_some()) || ((enabled_panel_ids.is_some()) || ((enabled_loops.is_some()) || ((enabled_workloads.is_some()) || (enabled_scheduled_jobs.is_some())))) {
        let mut stencil_env_overrides: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("FDAI_STENCIL_ENFORCE_INACTIVE_MENUS"), String::from("1"))]);
        if let Some(mut stencil_id) = stencil_id.clone() {
            stencil_env_overrides.insert(String::from("FDAI_STENCIL_ID"), stencil_id.clone());
        }
        if let Some(mut enabled_panel_ids) = enabled_panel_ids.clone() {
            stencil_env_overrides.insert(String::from("FDAI_STENCIL_ENABLED_PANELS"), ((enabled_panel_ids.clone()).into_iter().collect::<Vec<String>>()).join(","));
        }
        if let Some(mut enabled_loops) = enabled_loops.clone() {
            stencil_env_overrides.insert(String::from("FDAI_STENCIL_ENABLED_LOOPS"), ((enabled_loops.clone()).into_iter().collect::<Vec<String>>()).join(","));
        }
        if let Some(mut enabled_workloads) = enabled_workloads.clone() {
            stencil_env_overrides.insert(String::from("FDAI_STENCIL_ENABLED_WORKLOADS"), ((enabled_workloads.clone()).into_iter().collect::<Vec<String>>()).join(","));
        }
        if let Some(mut enabled_scheduled_jobs) = enabled_scheduled_jobs.clone() {
            stencil_env_overrides.insert(String::from("FDAI_STENCIL_ENABLED_JOBS"), ((enabled_scheduled_jobs.clone()).into_iter().collect::<Vec<String>>()).join(","));
        }
        let ff_json: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("fdai.stencil-feature-flags.v1")), (String::from("enforcement_mode"), String::from("fail-closed"))]);
    }
    if let Some(mut catalog_freshness) = catalog_freshness.clone() {
        let raw_key_ids: Option<String> = (catalog_freshness.clone()).get("root_key_ids").cloned();
        if !(true) {
            return Err("catalog_freshness.root_key_ids must be a sequence of ed25519-64hex IDs.");
        }
        let freshness_env: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("FDAI_CATALOG_FRESHNESS_METADATA_URL"), String::new()), (String::from("FDAI_CATALOG_FRESHNESS_ROOT_KEY_IDS"), String::new()), (String::from("FDAI_CATALOG_FRESHNESS_ROOT_THRESHOLD"), String::new()), (String::from("FDAI_CATALOG_FRESHNESS_REFRESH_SECONDS"), String::new())]);
        if (config_map_data.clone()).contains_key("core-control-plane-env") {
            let merged_core: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        }
    }
    if ((product.clone()) == (String::from("fdai"))) && ((workloads.clone()).contains_key("core-control-plane")) {
        service_accounts.insert(String::from("fdai-schema-migration"));
    }
    let prerequisites: PreExistingReferences = PreExistingReferences { service_accounts: (service_accounts.clone()).into_iter().collect::<Vec<String>>(), secret_provider_classes: (secret_provider_classes.clone()).into_iter().collect::<Vec<String>>(), config_maps: (config_maps.clone()).into_iter().collect::<Vec<String>>(), secrets: (secrets.clone()).into_iter().collect::<Vec<String>>(), ..Default::default() };
    Ok(GeneratedRuntimeTopology { prerequisites: Box::new(prerequisites.clone()), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn write_generated_runtime_bundle(mut topology_input_path: String, mut destination: String, mut installation_id: String, mut entity_id: String, mut product: String, mut namespace: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let generated: GeneratedRuntimeTopology = generate_fdai_runtime_bundle(std::collections::BTreeMap::new(), std::collections::BTreeMap::new(), installation_id.clone(), entity_id.clone(), product.clone(), namespace.clone(), String::new(), None, String::new(), None, None, None, None, None, None).unwrap_or_else(|_| Default::default());
    Ok(std::collections::BTreeMap::from([(String::from("schema_version"), String::from("fdai.generated-runtime-topology.v1")), (String::from("runtime_bundle_digest"), String::new()), (String::from("native_scope_digest"), String::new()), (String::from("topology_digest"), String::new()), (String::from("deployments"), String::new()), (String::from("services"), String::new()), (String::from("scheduled_jobs"), String::new()), (String::from("autoscalers"), String::new()), (String::from("components"), String::new()), (String::from("workload_handoff_inventory"), String::new()), (String::from("workload_handoff_tfvars"), String::new()), (String::from("workload_handoff_commands"), String::new()), (String::from("destination"), destination.clone())]))
}

