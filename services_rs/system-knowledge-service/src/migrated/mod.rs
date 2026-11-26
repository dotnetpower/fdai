pub mod application;
pub mod blob_ledger;
pub mod build_catalog;
pub mod catalog;
pub mod config;
pub mod ledger;
pub mod main_mod;
pub mod pkg_init;
pub mod render;
pub mod runtime;
pub mod search;
pub mod seeds;
pub mod server;
pub mod teams;
pub mod teams_auth;
pub mod teams_ingress;
pub mod teams_outgoing_webhook;
pub mod teams_publisher;

#[must_use]
pub fn build_migrated_router() -> fdai_contracts::http_compat::Router {
    fdai_contracts::http_compat::Router::new()
        .merge(application::build_axum_router())
}
