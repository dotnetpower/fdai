pub mod archive_audit_segments;
pub mod bind_existing_model;
pub mod check_local_prompt_source;
pub mod cleanup_local_broker;
pub mod collect_cost_governance_analytics;
pub mod compact_local_database;
pub mod ensure_local_models;
pub mod local_operations_materializer;
pub mod maintain_development_database;
pub mod materialize_authoritative_catalogs;
pub mod materialize_authoritative_settings;
pub mod prepare_operator_database_role;
pub mod prune_local_artifacts;
pub mod qualify_signed_catalog_custody_2498;
pub mod refresh_authoritative_inventory;
pub mod rehearse_inventory_shared_storage_cutover;
pub mod rehearse_operational_acceptance;
pub mod rehearse_operational_learning_qualification;
pub mod rehearse_stencil_epic_2524;
pub mod rehearse_x01_bundle_lifecycle_lineage;
pub mod reopen_rejected_approval;
pub mod report_database_growth;
pub mod reset_development_broker;
pub mod run_azure_policy_differential;
pub mod run_framework_rule_evidence;
pub mod supersede_duplicate_approvals;

#[must_use]
pub fn build_migrated_router() -> fdai_contracts::http_compat::Router {
    fdai_contracts::http_compat::Router::new()
        .merge(rehearse_stencil_epic_2524::build_axum_router())
}
