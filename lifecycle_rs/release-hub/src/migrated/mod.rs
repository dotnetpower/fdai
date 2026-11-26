pub mod api;
pub mod catalog_roles;
pub mod catalog_serialization;
pub mod cli;
pub mod database;
pub mod deployment_requests;
pub mod entra_session;
pub mod main_mod;
pub mod pkg_init;
pub mod registry_pipeline;
pub mod renewal;
pub mod role_tables;
pub mod root_ceremony;
pub mod stencil_grants;
pub mod stencil_product_decisions;
pub mod stencil_workflow_jobs;
pub mod stencils;
pub mod store;

#[must_use]
pub fn build_migrated_router() -> fdai_contracts::http_compat::Router {
    fdai_contracts::http_compat::Router::new()
        .merge(api::build_axum_router())
        .merge(stencil_workflow_jobs::build_axum_router())
}
