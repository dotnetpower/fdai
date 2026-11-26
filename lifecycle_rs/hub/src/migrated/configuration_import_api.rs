#[allow(unused_imports)]
use fdai_contracts::http_compat::{json_kv, routing::{delete, get, head, options, patch, post, put}, Json, Path, Query, Router, StatusCode, Value};

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SharedServiceState {
    pub service_available: bool,
    pub policy_current: bool,
    pub caller_role: String,
    pub max_payload_bytes: usize,
}

pub async fn handle_get_configuration_0() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "read"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_configuration_revisions_digest_1(Path(digest): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "read"), ("role_guard", "none"), ("byte_cap", "0"), ("digest", digest.as_str())])))
}

pub async fn handle_get_configuration_scope_requests_d_2(Path(digest): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "read"), ("role_guard", "none"), ("byte_cap", "0"), ("digest", digest.as_str())])))
}

pub async fn handle_post_configuration_operation_3(Path(operation): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::ACCEPTED, Json(json_kv(&[("handler", "change"), ("role_guard", "none"), ("byte_cap", "0"), ("operation", operation.as_str())])))
}

pub async fn handle_post_configuration_scope_operation_4(Path(operation): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::ACCEPTED, Json(json_kv(&[("handler", "change"), ("role_guard", "none"), ("byte_cap", "0"), ("operation", operation.as_str())])))
}

#[must_use]
pub fn build_axum_router() -> Router {
    Router::new()
        .route("/configuration", get(handle_get_configuration_0))
        .route("/configuration/revisions/{digest}", get(handle_get_configuration_revisions_digest_1))
        .route("/configuration-scope/requests/{digest}", get(handle_get_configuration_scope_requests_d_2))
        .route("/configuration/{operation}", post(handle_post_configuration_operation_3))
        .route("/configuration-scope/{operation}", post(handle_post_configuration_scope_operation_4))
}
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn configuration_routes(mut store: String, mut catalog: String, mut clock: String, mut recovery_authorization: Option<String>) -> Vec<String> {
    let root: String = String::from("/v1/installations/{installation_id}");
    Vec::new()
}

