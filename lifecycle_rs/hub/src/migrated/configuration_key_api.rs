#[allow(unused_imports)]
use fdai_contracts::http_compat::{json_kv, routing::{delete, get, head, options, patch, post, put}, Json, Path, Query, Router, StatusCode, Value};

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SharedServiceState {
    pub service_available: bool,
    pub policy_current: bool,
    pub caller_role: String,
    pub max_payload_bytes: usize,
}

pub async fn handle_get_v1_installations_installation_0(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "status"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

pub async fn handle_get_v1_installations_installation_1(Path((installation_id, digest)): Path<(String, String)>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "pending"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str()), ("digest", digest.as_str())])))
}

pub async fn handle_post_v1_installations_installation_2(Path((installation_id, operation)): Path<(String, String)>) -> (StatusCode, Json<Value>) {
    (StatusCode::ACCEPTED, Json(json_kv(&[("handler", "change"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str()), ("operation", operation.as_str())])))
}

#[must_use]
pub fn build_axum_router() -> Router {
    Router::new()
        .route("/v1/installations/{installation_id}/configuration-keys", get(handle_get_v1_installations_installation_0))
        .route("/v1/installations/{installation_id}/configuration-keys/requests/{digest}", get(handle_get_v1_installations_installation_1))
        .route("/v1/installations/{installation_id}/configuration-keys/{operation}", post(handle_post_v1_installations_installation_2))
}
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn key_routes(mut store: String, mut clock: String, mut authenticated: bool, mut recovery_authorization: Option<String>) -> Vec<String> {
    if store.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

