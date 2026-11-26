pub mod adoption_policy;
pub mod agent_artifacts;
pub mod api;
pub mod audit;
pub mod bootstrap;
pub mod catalog;
pub mod catalog_adoption;
pub mod catalog_import;
pub mod catalog_integrity;
pub mod catalog_integrity_state;
pub mod catalog_trust;
pub mod catalog_tuf_assessment;
pub mod cli;
pub mod configuration;
pub mod configuration_consumer;
pub mod configuration_import_api;
pub mod configuration_import_contracts;
pub mod configuration_import_models;
pub mod configuration_import_store;
pub mod configuration_import_trust;
pub mod configuration_key_api;
pub mod configuration_key_store;
pub mod configuration_keys;
pub mod database_inspection;
pub mod domain;
pub mod enrollment;
pub mod entitlement_handoff;
pub mod entity;
pub mod entra_session;
pub mod errors;
pub mod execution_settings;
pub mod execution_settings_api;
pub mod inventory;
pub mod local_channel_api;
pub mod local_channels;
pub mod mapping;
pub mod migrations;
pub mod models;
pub mod native_ownership;
pub mod native_ownership_api;
pub mod native_proofs;
pub mod native_transition;
pub mod native_transition_reconciliation;
pub mod operations;
pub mod operator_surfaces;
pub mod operator_surfaces_api;
pub mod pkg_init;
pub mod planning;
pub mod release_connection;
pub mod remote;
pub mod remote_auth;
pub mod remote_catalog;
pub mod reports;
pub mod rows;
pub mod schemas;
pub mod setup_api;
pub mod setup_start;
pub mod signing;
pub mod stencil_update_api;
pub mod stencil_update_flow;
pub mod store;

#[must_use]
pub fn build_migrated_router() -> fdai_contracts::http_compat::Router {
    fdai_contracts::http_compat::Router::new()
        .merge(api::build_axum_router())
        .merge(configuration_import_api::build_axum_router())
        .merge(configuration_key_api::build_axum_router())
        .merge(execution_settings_api::build_axum_router())
        .merge(local_channel_api::build_axum_router())
        .merge(native_ownership_api::build_axum_router())
        .merge(operator_surfaces_api::build_axum_router())
        .merge(release_connection::build_axum_router())
        .merge(remote::build_axum_router())
        .merge(remote_auth::build_axum_router())
        .merge(setup_api::build_axum_router())
        .merge(stencil_update_api::build_axum_router())
}
