#[allow(unused_imports)]
use fdai_contracts::http_compat::{json_kv, routing::{delete, get, head, options, patch, post, put}, Json, Path, Query, Router, StatusCode, Value};

pub const DEFAULT_MAX_SKEW_SECONDS: i64 = 300;
pub const DEFAULT_MAX_BODY_BYTES: i64 = 8192;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HilCallbackConfig {
    pub secret: String,
    pub max_skew_seconds: i64,
    pub max_body_bytes: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SharedServiceState {
    pub service_available: bool,
    pub policy_current: bool,
    pub caller_role: String,
    pub max_payload_bytes: usize,
}

pub async fn handle_post_hil_approval_id_decision_0(Path(approval_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "handler"), ("role_guard", "none"), ("byte_cap", "0"), ("approval_id", approval_id.as_str())])))
}

#[must_use]
pub fn build_axum_router() -> Router {
    Router::new()
        .route("/hil/{approval_id}/decision", post(handle_post_hil_approval_id_decision_0))
}
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn make_hil_callback_route(mut registry: Option<String>, mut outbox: Option<String>, mut config: Option<HilCallbackConfig>, mut authority: Option<String>, mut audit: Option<String>, mut context_reader: Option<String>, mut clock: Option<String>) -> String {
    if registry.is_none() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["DEFAULT_MAX_BODY_BYTES", "DEFAULT_MAX_SKEW_SECONDS", "HilCallbackConfig", "compute_hmac", "make_hil_callback_route"];
