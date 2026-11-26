//! Component Catalog domain (`/components`).

use axum::{extract::State, response::Response, routing::get, Router};
use serde_json::json;

use crate::{
    shell::{finalize_v4_html, html_response},
    AppState,
};

const TEMPLATE: &str = include_str!("../../templates/components.html");

pub fn router() -> Router<AppState> {
    Router::new().route("/components", get(page_components))
}

async fn page_components(State(state): State<AppState>) -> Response {
    let html = finalize_v4_html(
        TEMPLATE,
        "components",
        "components",
        &state.operator_url,
        json!({ "catalog": true }),
    );
    html_response(html)
}
