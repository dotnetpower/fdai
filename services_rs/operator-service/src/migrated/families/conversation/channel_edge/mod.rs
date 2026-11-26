pub mod application;
pub mod attachment_handoff;
pub mod attachment_ingestion;
pub mod composition;
pub mod entry;
pub mod environment;
pub mod models;
pub mod pipeline;
pub mod pipeline_contracts;
pub mod pkg_init;
pub mod presentation;
pub mod provider_adapters;
pub mod publishers;
pub mod queues;
pub mod renderers;
pub mod runtime;
pub mod slack_ingress;
pub mod teams_auth;
pub mod teams_ingress;
pub mod worker;

#[must_use]
pub fn build_migrated_router() -> fdai_contracts::http_compat::Router {
    fdai_contracts::http_compat::Router::new()
        .merge(runtime::build_axum_router())
}
