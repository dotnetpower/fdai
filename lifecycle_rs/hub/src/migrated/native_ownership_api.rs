#[allow(unused_imports)]
use fdai_contracts::http_compat::{json_kv, routing::{delete, get, head, options, patch, post, put}, Json, Path, Query, Router, StatusCode, Value};

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SharedServiceState {
    pub service_available: bool,
    pub policy_current: bool,
    pub caller_role: String,
    pub max_payload_bytes: usize,
}

pub async fn handle_post_v1_installations_installation_0(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::ACCEPTED, Json(json_kv(&[("handler", "submit"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

pub async fn handle_post_v1_installations_installation_1(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "accept"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

pub async fn handle_post_v1_installations_installation_2(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "approve_transition"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

pub async fn handle_post_v1_installations_installation_3(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "complete_transition"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

pub async fn handle_post_v1_installations_installation_4(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "approve_reconciliation"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

pub async fn handle_post_v1_installations_installation_5(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "complete_reconciliation"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

#[must_use]
pub fn build_axum_router() -> Router {
    Router::new()
        .route("/v1/installations/{installation_id}/native-proofs", post(handle_post_v1_installations_installation_0))
        .route("/v1/installations/{installation_id}/native-ownership", post(handle_post_v1_installations_installation_1))
        .route("/v1/installations/{installation_id}/native-transition-approval", post(handle_post_v1_installations_installation_2))
        .route("/v1/installations/{installation_id}/native-transition-completion", post(handle_post_v1_installations_installation_3))
        .route("/v1/installations/{installation_id}/native-transition-state-reconciliation-approval", post(handle_post_v1_installations_installation_4))
        .route("/v1/installations/{installation_id}/native-transition-state-reconciliation", post(handle_post_v1_installations_installation_5))
}
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn native_ownership_routes(mut store: String, mut clock: String, mut authenticated: bool, mut transition_key: Option<String>) -> Vec<String> {
    if store.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

