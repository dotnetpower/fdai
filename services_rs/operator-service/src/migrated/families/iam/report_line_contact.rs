#[allow(unused_imports)]
use fdai_contracts::http_compat::{json_kv, routing::{delete, get, head, options, patch, post, put}, Json, Path, Query, Router, StatusCode, Value};

pub const MAX_BODY_BYTES: i64 = 1024;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SharedServiceState {
    pub service_available: bool,
    pub policy_current: bool,
    pub caller_role: String,
    pub max_payload_bytes: usize,
}

pub async fn handle_get_hil_report_line_contact_reques_0() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "list_report_line_contacts"), ("role_guard", "reader"), ("byte_cap", "0")])))
}

pub async fn handle_post_hil_approval_id_report_line_co_1(Path(approval_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::ACCEPTED, Json(json_kv(&[("handler", "post_report_line_contact"), ("role_guard", "reader"), ("byte_cap", "0"), ("approval_id", approval_id.as_str())])))
}

#[must_use]
pub fn build_axum_router() -> Router {
    Router::new()
        .route("/hil/report-line-contact-requests", get(handle_get_hil_report_line_contact_reques_0))
        .route("/hil/{approval_id}/report-line-contact", post(handle_post_hil_approval_id_report_line_co_1))
}
pub const IDEMPOTENCY_KEY: &str = "^[A-Za-z0-9._:-]{1,256}$";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn make_report_line_contact_route(mut authorize: String, mut outbox: Option<String>) -> Vec<String> {
    if authorize.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["make_report_line_contact_route"];
