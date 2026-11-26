pub mod application;
pub mod application_store;
pub mod article_extended;
pub mod article_tree;
pub mod azure_templates;
pub mod collector;
pub mod composition;
pub mod http;
pub mod main_mod;
pub mod normalization;
pub mod pkg_init;
pub mod policy;
pub mod projection;
pub mod review;
pub mod review_contracts;
pub mod review_io;
pub mod review_worker;
pub mod scheduler;
pub mod service;
pub mod store;
pub mod structured_normalization;
pub mod transport;

#[must_use]
pub fn build_migrated_router() -> fdai_contracts::http_compat::Router {
    fdai_contracts::http_compat::Router::new()
        .merge(http::build_axum_router())
}
