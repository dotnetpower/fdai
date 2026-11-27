//! Static asset and icon serving with strict path-traversal containment.

use axum::{
    extract::{Path as AxumPath, State},
    http::{header, StatusCode},
    response::{IntoResponse, Response},
    routing::get,
    Router,
};
use std::path::{Component, Path, PathBuf};

use crate::AppState;

pub const SHARED_CSS: &str = include_str!("../assets/css/fdai-console-shared.css");
pub const SHARED_SHELL_JS: &str = include_str!("../assets/js/fdai-console-shell.js");
pub const LIVE_CLIENT_JS: &str = include_str!("../assets/js/fdai-console-live.js");
pub const CHAT_ENGINE_JS: &str = include_str!("../assets/js/fdai-chat-engine.js");
pub const ADVISOR_INLINE_JS: &str = include_str!("../assets/js/fdai-advisor-inline.js");

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/assets/fdai-console-shared.css", get(serve_shared_css))
        .route("/fdai-console-shared.css", get(serve_shared_css))
        .route("/assets/fdai-console-shell.js", get(serve_shared_shell_js))
        .route("/fdai-console-shell.js", get(serve_shared_shell_js))
        .route("/assets/fdai-console-live.js", get(serve_live_client_js))
        .route("/fdai-console-live.js", get(serve_live_client_js))
        .route("/assets/fdai-chat-engine.js", get(serve_chat_engine_js))
        .route("/fdai-chat-engine.js", get(serve_chat_engine_js))
        .route("/assets/fdai-advisor-inline.js", get(serve_advisor_inline_js))
        .route("/fdai-advisor-inline.js", get(serve_advisor_inline_js))
        .route("/brand/{*path}", get(serve_brand_asset))
        .route("/azure-icons/{*path}", get(serve_azure_icon))
        .route("/agent-icons/{*path}", get(serve_agent_icon))
}

async fn serve_shared_css() -> Response {
    (
        StatusCode::OK,
        [
            (header::CONTENT_TYPE, "text/css; charset=utf-8"),
            (header::CACHE_CONTROL, "no-store"),
        ],
        SHARED_CSS,
    )
        .into_response()
}

async fn serve_shared_shell_js() -> Response {
    (
        StatusCode::OK,
        [
            (header::CONTENT_TYPE, "application/javascript; charset=utf-8"),
            (header::CACHE_CONTROL, "no-store"),
        ],
        SHARED_SHELL_JS,
    )
        .into_response()
}

async fn serve_live_client_js() -> Response {
    (
        StatusCode::OK,
        [
            (header::CONTENT_TYPE, "application/javascript; charset=utf-8"),
            (header::CACHE_CONTROL, "no-store"),
        ],
        LIVE_CLIENT_JS,
    )
        .into_response()
}

async fn serve_chat_engine_js() -> Response {
    (
        StatusCode::OK,
        [
            (header::CONTENT_TYPE, "application/javascript; charset=utf-8"),
            (header::CACHE_CONTROL, "no-store"),
        ],
        CHAT_ENGINE_JS,
    )
        .into_response()
}

async fn serve_advisor_inline_js() -> Response {
    (
        StatusCode::OK,
        [
            (header::CONTENT_TYPE, "application/javascript; charset=utf-8"),
            (header::CACHE_CONTROL, "no-store"),
        ],
        ADVISOR_INLINE_JS,
    )
        .into_response()
}

async fn serve_brand_asset(
    State(state): State<AppState>,
    AxumPath(rel): AxumPath<String>,
) -> Response {
    serve_contained_file(&state.brand_dir, &rel).await
}

async fn serve_azure_icon(
    State(state): State<AppState>,
    AxumPath(rel): AxumPath<String>,
) -> Response {
    serve_contained_file(&state.azure_icons_dir, &rel).await
}

async fn serve_agent_icon(
    State(state): State<AppState>,
    AxumPath(rel): AxumPath<String>,
) -> Response {
    serve_contained_file(&state.agent_icons_dir, &rel).await
}

fn sanitize_relative_path(raw: &str) -> Option<PathBuf> {
    let trimmed = raw.trim_start_matches('/');
    if trimmed.is_empty() || trimmed.contains('\0') {
        return None;
    }
    let mut clean = PathBuf::new();
    for comp in Path::new(trimmed).components() {
        match comp {
            Component::Normal(seg) => clean.push(seg),
            Component::CurDir => {}
            Component::ParentDir | Component::RootDir | Component::Prefix(_) => return None,
        }
    }
    if clean.as_os_str().is_empty() {
        None
    } else {
        Some(clean)
    }
}

fn content_type_for_path(path: &Path) -> &'static str {
    match path.extension().and_then(|e| e.to_str()).unwrap_or("") {
        "svg" => "image/svg+xml",
        "png" => "image/png",
        "ico" => "image/x-icon",
        "css" => "text/css; charset=utf-8",
        "js" => "application/javascript; charset=utf-8",
        "json" => "application/json; charset=utf-8",
        "woff2" => "font/woff2",
        _ => "application/octet-stream",
    }
}

async fn serve_contained_file(base_dir: &Path, rel: &str) -> Response {
    let Some(clean_rel) = sanitize_relative_path(rel) else {
        return (StatusCode::FORBIDDEN, "Forbidden").into_response();
    };
    let candidate = base_dir.join(clean_rel);
    let Ok(base_canon) = tokio::fs::canonicalize(base_dir).await else {
        return (StatusCode::NOT_FOUND, "Not Found").into_response();
    };
    let Ok(file_canon) = tokio::fs::canonicalize(&candidate).await else {
        return (StatusCode::NOT_FOUND, "Not Found").into_response();
    };
    if !file_canon.starts_with(&base_canon) {
        return (StatusCode::FORBIDDEN, "Forbidden").into_response();
    }
    match tokio::fs::read(&file_canon).await {
        Ok(bytes) => (
            StatusCode::OK,
            [
                (header::CONTENT_TYPE, content_type_for_path(&file_canon)),
                (header::CACHE_CONTROL, "public, max-age=300"),
            ],
            bytes,
        )
            .into_response(),
        Err(_) => (StatusCode::NOT_FOUND, "Not Found").into_response(),
    }
}
