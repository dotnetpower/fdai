#[allow(unused_imports)]
use fdai_contracts::http_compat::{json_kv, routing::{delete, get, head, options, patch, post, put}, Json, Path, Query, Router, StatusCode, Value};

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SharedServiceState {
    pub service_available: bool,
    pub policy_current: bool,
    pub caller_role: String,
    pub max_payload_bytes: usize,
}

pub async fn handle_get_v1_catalog_local_channels_0() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "view"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_post_v1_catalog_local_channels_1() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "add"), ("role_guard", "none"), ("byte_cap", "0")])))
}

#[must_use]
pub fn build_axum_router() -> Router {
    Router::new()
        .route("/v1/catalog/local-channels", get(handle_get_v1_catalog_local_channels_0).post(handle_post_v1_catalog_local_channels_1))
}
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn local_channel_routes(mut catalog: String, mut clock: String) -> Vec<String> {
    if catalog.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

