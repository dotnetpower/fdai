#[allow(unused_imports)]
use fdai_contracts::http_compat::{json_kv, routing::{delete, get, head, options, patch, post, put}, Json, Path, Query, Router, StatusCode, Value};

pub const MAX_BODY: i64 = 2097152;
pub const MAX_STENCIL_BODY: i64 = 65536;
pub const MAX_CATALOG_VIEW_BYTES: i64 = 16777216;
pub const MAX_INTAKE_CONCURRENCY: i64 = 8;
pub const INTAKE_BODY_TIMEOUT_SECONDS: i64 = 10;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SharedServiceState {
    pub service_available: bool,
    pub policy_current: bool,
    pub caller_role: String,
    pub max_payload_bytes: usize,
}

pub async fn handle_get_auth_config_0() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "inline_lambda"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_v1_auth_session_1() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "auth_session"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_post_v1_auth_entra_login_2() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "entra_login"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_post_v1_auth_entra_logout_3() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "entra_logout"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_v2_4() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "oci_v2_base"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_head_v2_5() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "oci_v2_base"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_v2_6() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "oci_v2_base"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_head_v2_7() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "oci_v2_base"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_v2_catalog_8() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "oci_v2_catalog"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_head_v2_catalog_9() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "oci_v2_catalog"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_v2_fdai_component_manifests_re_10(Path((component, reference)): Path<(String, String)>) -> (StatusCode, Json<Value>) {
    (StatusCode::CREATED, Json(json_kv(&[("handler", "oci_v2_manifest"), ("role_guard", "none"), ("byte_cap", "0"), ("component", component.as_str()), ("reference", reference.as_str())])))
}

pub async fn handle_head_v2_fdai_component_manifests_re_11(Path((component, reference)): Path<(String, String)>) -> (StatusCode, Json<Value>) {
    (StatusCode::CREATED, Json(json_kv(&[("handler", "oci_v2_manifest"), ("role_guard", "none"), ("byte_cap", "0"), ("component", component.as_str()), ("reference", reference.as_str())])))
}

pub async fn handle_put_v2_fdai_component_manifests_re_12(Path((component, reference)): Path<(String, String)>) -> (StatusCode, Json<Value>) {
    (StatusCode::CREATED, Json(json_kv(&[("handler", "oci_v2_manifest"), ("role_guard", "none"), ("byte_cap", "0"), ("component", component.as_str()), ("reference", reference.as_str())])))
}

pub async fn handle_get_v1_registry_images_13() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "registry_images"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_healthz_14() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "inline_lambda"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_head_healthz_15() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "inline_lambda"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_readyz_16() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "readyz"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_head_readyz_17() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "readyz"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_v1_catalog_18() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "catalog"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_head_v1_catalog_19() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "catalog"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_v1_catalog_export_20() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "export"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_head_v1_catalog_export_21() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "export"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_v1_catalog_metadata_22() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "metadata"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_head_v1_catalog_metadata_23() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "metadata"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_post_v1_catalog_renew_24() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "change"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_v1_deployment_requests_25() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "deployment_requests"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_post_v1_deployment_requests_26() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "deployment_requests"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_get_v1_stencils_27() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "stencils_catalog"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_post_v1_stencils_compose_28() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "stencils_compose"), ("role_guard", "none"), ("byte_cap", "0")])))
}

pub async fn handle_post_v1_releases_param_0_action_29(Path((param_0, action)): Path<(String, String)>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "change"), ("role_guard", "none"), ("byte_cap", "0"), ("param_0", param_0.as_str()), ("action", action.as_str())])))
}

pub async fn handle_post_v1_capabilities_param_0_action_30(Path((param_0, action)): Path<(String, String)>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "change"), ("role_guard", "none"), ("byte_cap", "0"), ("param_0", param_0.as_str()), ("action", action.as_str())])))
}

pub async fn handle_get_path_31(Path(path): Path<String>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(json_kv(&[("handler", "index"), ("role_guard", "none"), ("byte_cap", "0"), ("path", path.as_str())])))
}

#[must_use]
pub fn build_axum_router() -> Router {
    Router::new()
        .route("/auth/config", get(handle_get_auth_config_0))
        .route("/v1/auth/session", get(handle_get_v1_auth_session_1))
        .route("/v1/auth/entra/login", post(handle_post_v1_auth_entra_login_2))
        .route("/v1/auth/entra/logout", post(handle_post_v1_auth_entra_logout_3))
        .route("/v2", get(handle_get_v2_4).head(handle_head_v2_5))
        .route("/v2/", get(handle_get_v2_6).head(handle_head_v2_7))
        .route("/v2/_catalog", get(handle_get_v2_catalog_8).head(handle_head_v2_catalog_9))
        .route("/v2/fdai/{component}/manifests/{reference}", get(handle_get_v2_fdai_component_manifests_re_10).head(handle_head_v2_fdai_component_manifests_re_11).put(handle_put_v2_fdai_component_manifests_re_12))
        .route("/v1/registry/images", get(handle_get_v1_registry_images_13))
        .route("/healthz", get(handle_get_healthz_14).head(handle_head_healthz_15))
        .route("/readyz", get(handle_get_readyz_16).head(handle_head_readyz_17))
        .route("/v1/catalog", get(handle_get_v1_catalog_18).head(handle_head_v1_catalog_19))
        .route("/v1/catalog/export", get(handle_get_v1_catalog_export_20).head(handle_head_v1_catalog_export_21))
        .route("/v1/catalog/metadata", get(handle_get_v1_catalog_metadata_22).head(handle_head_v1_catalog_metadata_23))
        .route("/v1/catalog/renew", post(handle_post_v1_catalog_renew_24))
        .route("/v1/deployment-requests", get(handle_get_v1_deployment_requests_25).post(handle_post_v1_deployment_requests_26))
        .route("/v1/stencils", get(handle_get_v1_stencils_27))
        .route("/v1/stencils/compose", post(handle_post_v1_stencils_compose_28))
        .route("/v1/releases/{param_0}}/{action}", post(handle_post_v1_releases_param_0_action_29))
        .route("/v1/capabilities/{*param_0}}/{action}", post(handle_post_v1_capabilities_param_0_action_30))
        .route("/{*path}", get(handle_get_path_31))
        .nest("/assets", Router::new().route("/", get(|| {})))
        .nest("/brand", Router::new().route("/", get(|| {})))
}
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn create_app(mut store: String, mut static_dir: Option<String>, mut remote_auth: Option<String>, mut remote_origin: Option<String>, mut grant_issuer_public_keys: Vec<String>) -> Result<String, &'static str> {
    if store.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

