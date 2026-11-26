#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn local_fake_llm_bindings() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn default_container(mut config: String) -> String {
    if config.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn bind_decision_evidence_admission(mut container: String, mut state_store: String, mut clock: Option<String>) -> String {
    if container.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn bind_azure_decision_evidence_admission(mut container: String, mut container_url: String, mut identity: String, mut http_client: String) -> String {
    if container.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn bind_azure_monitor_logs(mut container: String, mut config: String, mut identity: String, mut http_client: String) -> String {
    if container.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn bind_embedding_knowledge_source(mut container: String, mut max_chars: i64, mut overlap: i64) -> String {
    if container.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn bind_pgvector_knowledge_source(mut container: String, mut config: String, mut secrets: String) -> String {
    if container.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn bind_drop_directory_manual_source(mut container: String, mut root: String, mut glob: String) -> String {
    if container.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_pricing_table(mut path: String) -> Result<String, &'static str> {
    if path.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn default_container_from_env(mut environ: Option<std::collections::BTreeMap<String, String>>) -> String {
    default_container(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureWireOverrides", "Container", "LlmBindings", "LlmBindingsUnavailableError", "OperationalReadinessService", "SemanticQueryRuntimeComposition", "SkillDisclosureStartupBinding", "SkillDisclosureStartupReadiness", "TrajectoryRuntime", "attach_metric_provider", "attach_observation_providers", "attach_telemetry_workspace_resolver", "bind_browser_evidence", "bind_configuration_drift", "bind_decision_evidence_admission", "bind_context_selection_shadow", "bind_execution_authorization", "bind_execution_backends", "bind_resolved_models_revision", "bind_azure_llm_bindings", "bind_azure_decision_evidence_admission", "bind_azure_ontology_distiller", "bind_azure_operational_evidence", "bind_azure_devops_change_feed", "bind_github_change_feed", "build_semantic_query_runtime", "build_t1_mini_probe", "compose_azure_semantic_query_runtime", "compose_resource_state_shadow_hook", "compose_runtime_skill_disclosure_startup", "default_container", "default_container_from_env", "install_capability_bundle", "load_pricing_table", "load_execution_backend_registry_file", "publish_trusted_skill_disclosure_snapshots", "wire_azure_container", "wire_trajectory_runtime"];
