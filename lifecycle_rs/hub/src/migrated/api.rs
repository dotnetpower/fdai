#[allow(unused_imports)]
use fdai_contracts::http_compat::{json_kv, routing::{delete, get, head, options, patch, post, put}, Json, Path, Query, Router, StatusCode, Value};

pub const MAX_REPORT_BYTES: i64 = 16384;
pub const MAX_ENROLLMENT_BYTES: i64 = 65536;
pub const MAX_STATE_BYTES: i64 = 65536;
pub const MAX_APPROVAL_BYTES: i64 = 4096;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SharedServiceState {
    pub service_available: bool,
    pub policy_current: bool,
    pub caller_role: String,
    pub max_payload_bytes: usize,
}

pub async fn handle_get_auth_config_0() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "auth_config"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_auth_session_1() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "auth_session"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_post_auth_entra_login_2() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "entra_login"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_post_auth_entra_logout_3() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "entra_logout"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_v1_auth_session_4() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "auth_session"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_post_v1_auth_entra_login_5() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "entra_login"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_post_v1_auth_entra_logout_6() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "entra_logout"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_healthz_7() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "healthz"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_post_v1_installations_installation_8(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "post_enrollment"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

pub async fn handle_get_v1_installations_installation_9(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::NO_CONTENT, Json(json_kv(&[("handler", "get_plan"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

pub async fn handle_get_v1_installations_installation_10(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::NO_CONTENT, Json(json_kv(&[("handler", "get_entitlement_handoff"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

pub async fn handle_post_v1_installations_installation_11(Path((installation_id, plan_id)): Path<(String, String)>) -> (StatusCode, Json<Value>) {
    (StatusCode::ACCEPTED, Json(json_kv(&[("handler", "post_report"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str()), ("plan_id", plan_id.as_str())])))
}

pub async fn handle_post_v1_installations_installation_12(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::ACCEPTED, Json(json_kv(&[("handler", "post_state"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

pub async fn handle_get_v1_installations_13() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "list_installations"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_v1_configurations_14() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "list_configurations"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_v1_audit_15() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "list_audit"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_v1_installations_installation_16(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "get_installation"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

pub async fn handle_get_v1_installations_installation_17(Path((installation_id, plan_id)): Path<(String, String)>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "get_plan_detail"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str()), ("plan_id", plan_id.as_str())])))
}

pub async fn handle_post_v1_installations_installation_18(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "post_suppression"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

pub async fn handle_post_v1_installations_installation_19(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "post_lift_suppression"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

pub async fn handle_get_v1_enrollments_pending_20() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "list_pending"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_v1_enrollments_pending_install_21(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "get_pending"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

pub async fn handle_post_v1_installations_installation_22(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "post_approve"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

pub async fn handle_post_v1_installations_installation_23(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "post_reject"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

pub async fn handle_get_v1_enrollments_bindable_24() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "list_bindable"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_post_v1_installations_installation_25(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "post_agent_enrollment"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

pub async fn handle_post_v1_enrollments_installation_id_26(Path(installation_id): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "post_operator_enrollment"), ("role_guard", "none"), ("byte_cap", "0"), ("installation_id", installation_id.as_str())])))
}

pub async fn handle_get_path_27(Path(path): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "serve_ui"), ("role_guard", "none"), ("byte_cap", "0"), ("path", path.as_str())])))
}

#[must_use]
pub fn build_axum_router() -> Router {
    Router::new()
        .route("/auth/config", get(handle_get_auth_config_0))
        .route("/auth/session", get(handle_get_auth_session_1))
        .route("/auth/entra/login", post(handle_post_auth_entra_login_2))
        .route("/auth/entra/logout", post(handle_post_auth_entra_logout_3))
        .route("/v1/auth/session", get(handle_get_v1_auth_session_4))
        .route("/v1/auth/entra/login", post(handle_post_v1_auth_entra_login_5))
        .route("/v1/auth/entra/logout", post(handle_post_v1_auth_entra_logout_6))
        .route("/healthz", get(handle_get_healthz_7))
        .route("/v1/installations/{installation_id}/enrollment", post(handle_post_v1_installations_installation_8))
        .route("/v1/installations/{installation_id}/plan", get(handle_get_v1_installations_installation_9))
        .route("/v1/installations/{installation_id}/entitlement-handoff", get(handle_get_v1_installations_installation_10))
        .route("/v1/installations/{installation_id}/plans/{plan_id}/reports", post(handle_post_v1_installations_installation_11))
        .route("/v1/installations/{installation_id}/state", post(handle_post_v1_installations_installation_12))
        .route("/v1/installations", get(handle_get_v1_installations_13))
        .route("/v1/configurations", get(handle_get_v1_configurations_14))
        .route("/v1/audit", get(handle_get_v1_audit_15))
        .route("/v1/installations/{installation_id}", get(handle_get_v1_installations_installation_16))
        .route("/v1/installations/{installation_id}/plans/{plan_id}", get(handle_get_v1_installations_installation_17))
        .route("/v1/installations/{installation_id}/suppressions", post(handle_post_v1_installations_installation_18))
        .route("/v1/installations/{installation_id}/suppressions/lift", post(handle_post_v1_installations_installation_19))
        .route("/v1/enrollments/pending", get(handle_get_v1_enrollments_pending_20))
        .route("/v1/enrollments/pending/{installation_id}", get(handle_get_v1_enrollments_pending_install_21))
        .route("/v1/installations/{installation_id}/enrollment/approve", post(handle_post_v1_installations_installation_22))
        .route("/v1/installations/{installation_id}/enrollment/reject", post(handle_post_v1_installations_installation_23))
        .route("/v1/enrollments/bindable", get(handle_get_v1_enrollments_bindable_24))
        .route("/v1/installations/{installation_id}/enrollment-request", post(handle_post_v1_installations_installation_25))
        .route("/v1/enrollments/{installation_id}/requests", post(handle_post_v1_enrollments_installation_id_26))
        .route("/{*path}", get(handle_get_path_27))
}
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn create_app(mut store: String, mut clock: String, mut verify_proof: String, mut static_dir: Option<String>, mut remote_auth: Option<String>, mut remote_origin: Option<String>, mut transition_key: Option<String>, mut release_hub_endpoint: Option<String>, mut installation_console_urls: Option<std::collections::BTreeMap<String, String>>, mut auto_workstation_auth: bool, mut stencil_export_public_key: Option<String>, mut stencil_grant_issuer_public_keys: Vec<String>) -> String {
    if store.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn decision_request_error(mut request: String) -> Option<String> {
    if request.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn read_limited(mut request: String, mut limit: i64) -> Option<Vec<u8>> {
    if request.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn error(mut status_code: i64, mut reason_code: String) -> String {
    if reason_code.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["DEFAULT_UI_DIST", "GovernedEntitlementRotationReceipt", "HubEntitlementHandoffStore", "MAX_APPROVAL_BYTES", "MAX_ENROLLMENT_BYTES", "MAX_REPORT_BYTES", "MAX_STATE_BYTES", "OpaqueEntitlementCarrierHandoff", "create_app"];
