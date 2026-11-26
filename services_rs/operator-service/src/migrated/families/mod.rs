pub mod aks_commerce;
pub mod conversation;
pub mod cost_governance;
pub mod iam;
pub mod operations;
pub mod workflow;

#[must_use]
pub fn build_migrated_router() -> fdai_contracts::http_compat::Router {
    fdai_contracts::http_compat::Router::new()
        .merge(conversation::build_migrated_router())
        .merge(iam::build_migrated_router())
}
