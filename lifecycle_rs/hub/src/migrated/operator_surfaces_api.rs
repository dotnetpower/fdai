#[allow(unused_imports)]
use fdai_contracts::http_compat::{json_kv, routing::{delete, get, head, options, patch, post, put}, Json, Path, Query, Router, StatusCode, Value};

pub const MAX_SURFACE_BODY_BYTES: i64 = 16384;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SharedServiceState {
    pub service_available: bool,
    pub policy_current: bool,
    pub caller_role: String,
    pub max_payload_bytes: usize,
}

pub async fn handle_get_v1_commands_0() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "get_commands"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_post_v1_installations_installation_1(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::CREATED, Json(json_kv(&[("handler", "post_command"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

pub async fn handle_get_v1_confirmations_2() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "get_confirmations"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_post_v1_installations_installation_3(Path((installation_id, plan_id)): Path<(String, String)>) -> (StatusCode, Json<Value>) {
    (StatusCode::CREATED, Json(json_kv(&[("handler", "post_confirmation_proposal"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str()), ("plan_id", plan_id.as_str())])))
}

pub async fn handle_post_v1_installations_installation_4(Path((installation_id, plan_id)): Path<(String, String)>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "post_confirmation_decision"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str()), ("plan_id", plan_id.as_str())])))
}

pub async fn handle_get_v1_bundle_imports_5() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "get_bundle_imports"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_post_v1_bundle_imports_6() -> (StatusCode, Json<Value>) {
    (StatusCode::CREATED, Json(json_kv(&[("handler", "post_bundle_import"), ("role_guard", "none"), ("byte_cap", "0")])))
}

#[must_use]
pub fn build_axum_router() -> Router {
    Router::new()
        .route("/v1/commands", get(handle_get_v1_commands_0))
        .route("/v1/installations/{installation_id}/commands", post(handle_post_v1_installations_installation_1))
        .route("/v1/confirmations", get(handle_get_v1_confirmations_2))
        .route("/v1/installations/{installation_id}/plans/{plan_id}/confirmations", post(handle_post_v1_installations_installation_3))
        .route("/v1/installations/{installation_id}/plans/{plan_id}/confirmations/decision", post(handle_post_v1_installations_installation_4))
        .route("/v1/bundle-imports", get(handle_get_v1_bundle_imports_5).post(handle_post_v1_bundle_imports_6))
}
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn operator_surface_routes(mut store: String, mut clock: String) -> Vec<String> {
    if store.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

