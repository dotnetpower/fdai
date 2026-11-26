pub mod agent;
pub mod automation;
pub mod benchmarking;
pub mod catalog;
pub mod deployment;
pub mod evaluation;
pub mod governance;
pub mod integrity;
pub mod operations;
pub mod quality;
pub mod pkg_init;

#[must_use]
pub fn build_migrated_router() -> fdai_contracts::http_compat::Router {
    fdai_contracts::http_compat::Router::new()
        .merge(deployment::build_migrated_router())
}
