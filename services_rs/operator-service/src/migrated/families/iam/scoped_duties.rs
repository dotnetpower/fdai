#[allow(unused_imports)]
use fdai_contracts::http_compat::{json_kv, routing::{delete, get, head, options, patch, post, put}, Json, Path, Query, Router, StatusCode, Value};

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SharedServiceState {
    pub service_available: bool,
    pub policy_current: bool,
    pub caller_role: String,
    pub max_payload_bytes: usize,
}

pub async fn handle_get_handover_scoped_duties_catalog_0() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "scoped_catalog"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_handover_scoped_duties_1() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "scoped_projection"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_post_handover_scoped_duty_cases_2() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "create_scoped_case"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_handover_scoped_duty_cases_cas_3(Path(case_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "get_scoped_case"), ("role_guard", "none"), ("byte_cap", "0"), ("case_id", case_id.as_str())])))
}

pub async fn handle_post_handover_scoped_duty_cases_cas_4(Path(case_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "submit_scoped_case"), ("role_guard", "none"), ("byte_cap", "0"), ("case_id", case_id.as_str())])))
}

pub async fn handle_post_handover_scoped_duty_cases_cas_5(Path(case_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "review_scoped_case"), ("role_guard", "none"), ("byte_cap", "0"), ("case_id", case_id.as_str())])))
}

#[must_use]
pub fn build_axum_router() -> Router {
    Router::new()
        .route("/handover/scoped-duties/catalog", get(handle_get_handover_scoped_duties_catalog_0))
        .route("/handover/scoped-duties", get(handle_get_handover_scoped_duties_1))
        .route("/handover/scoped-duty-cases", post(handle_post_handover_scoped_duty_cases_2))
        .route("/handover/scoped-duty-cases/{case_id}", get(handle_get_handover_scoped_duty_cases_cas_3))
        .route("/handover/scoped-duty-cases/{case_id}/submit", post(handle_post_handover_scoped_duty_cases_cas_4))
        .route("/handover/scoped-duty-cases/{case_id}/review", post(handle_post_handover_scoped_duty_cases_cas_5))
}
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn make_scoped_duty_routes(mut outbox: Option<String>, mut authorize: String) -> Result<Vec<String>, &'static str> {
    if outbox.is_none() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["make_scoped_duty_routes"];
