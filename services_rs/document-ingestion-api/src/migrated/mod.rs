pub mod adapters;
pub mod cloud_knowledge;
pub mod access;
pub mod application;
pub mod auth;
pub mod channel_attachment;
pub mod channel_attachment_http;
pub mod channel_attachment_main;
pub mod channel_attachment_production;
pub mod composition;
pub mod contract_codecs;
pub mod deletion;
pub mod document_replacement;
pub mod download;
pub mod download_authorization;
pub mod http;
pub mod ingestion;
pub mod main_mod;
pub mod pkg_init;
pub mod preview;
pub mod production;
pub mod providers;
pub mod retention;
pub mod runtime;
pub mod server;
pub mod sharepoint_connector;
pub mod state_machine;

#[must_use]
pub fn build_migrated_router() -> fdai_contracts::http_compat::Router {
    fdai_contracts::http_compat::Router::new()
        .merge(channel_attachment_http::build_axum_router())
        .merge(http::build_axum_router())
        .merge(cloud_knowledge::build_migrated_router())
}
