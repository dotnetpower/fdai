pub mod azure;
pub mod local;
pub mod release;
pub mod scenario_lab;
pub mod service;
pub mod system_knowledge;

#[must_use]
pub fn build_migrated_router() -> fdai_contracts::http_compat::Router {
    fdai_contracts::http_compat::Router::new()
        .merge(local::build_migrated_router())
}
