pub mod channel_edge;
pub mod background_tasks;
pub mod channel_delivery_models;
pub mod channel_message_ledger;
pub mod contracts;
pub mod conversation_history;
pub mod conversation_search;
pub mod document_export;
pub mod document_refs;
pub mod factory;
pub mod handover_binding;
pub mod inline_images;
pub mod manifest;
pub mod pkg_init;
pub mod post_turn_review;
pub mod postgres_channel_binding;
pub mod postgres_channel_delivery;
pub mod postgres_document_refs;
pub mod presentation_artifact_domains;
pub mod presentation_artifact_renderers;
pub mod presentation_artifact_v2;
pub mod presentation_artifact_v3;
pub mod presentation_planner;
pub mod presentation_rows;
pub mod result_handles;
pub mod semantic_assurance_presentation;
pub mod semantic_authentication_receipts;
pub mod semantic_document_presentation;
pub mod semantic_incident_presentation;
pub mod semantic_model_call_presentation;
pub mod semantic_progress_relay;
pub mod semantic_runtime_activity;
pub mod semantic_trajectory_presentation;
pub mod semantic_turn;
pub mod semantic_turn_presentation;
pub mod semantic_turn_runtime;
pub mod semantic_work_progress_presentation;
pub mod subscription_scope_presentation;
pub mod t1_model_health;
pub mod transport;
pub mod user_context;

#[must_use]
pub fn build_migrated_router() -> fdai_contracts::http_compat::Router {
    fdai_contracts::http_compat::Router::new()
        .merge(channel_edge::build_migrated_router())
}
