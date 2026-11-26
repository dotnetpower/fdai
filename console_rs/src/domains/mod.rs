//! Domain registry uniting all 8 top-level menus (65 panels) + Component Catalog.

pub mod agents;
pub mod chat;
pub mod components;
pub mod evidence;
pub mod governance;
pub mod labs;
pub mod operations;
pub mod overview;
pub mod settings;

use axum::{extract::State, routing::get, Router};
use serde_json::{json, Value};

use crate::{
    shell::{canonical_panel_path, finalize_v4_html, html_response},
    AppState,
};

const TPL_OVERVIEW: &str = include_str!("../../templates/overview.html");
const TPL_OPERATIONS: &str = include_str!("../../templates/operations.html");
const TPL_AGENTS: &str = include_str!("../../templates/agents.html");
const TPL_GOVERNANCE: &str = include_str!("../../templates/governance.html");
const TPL_EVIDENCE: &str = include_str!("../../templates/evidence.html");
const TPL_SETTINGS: &str = include_str!("../../templates/settings.html");
const TPL_LABS: &str = include_str!("../../templates/labs.html");

fn domain_template(domain: &str) -> (&'static str, &'static [&'static str]) {
    match domain {
        "overview" => (TPL_OVERVIEW, overview::panel_ids()),
        "operations" => (TPL_OPERATIONS, operations::panel_ids()),
        "agents" => (TPL_AGENTS, agents::panel_ids()),
        "governance" => (TPL_GOVERNANCE, governance::panel_ids()),
        "evidence" => (TPL_EVIDENCE, evidence::panel_ids()),
        "settings" => (TPL_SETTINGS, settings::panel_ids()),
        _ => (TPL_LABS, labs::panel_ids()),
    }
}

fn register_clean_panel_routes(mut router: Router<AppState>) -> Router<AppState> {
    let groups: [(&'static str, &'static [&'static str]); 7] = [
        ("overview", overview::panel_ids()),
        ("operations", operations::panel_ids()),
        ("agents", agents::panel_ids()),
        ("governance", governance::panel_ids()),
        ("evidence", evidence::panel_ids()),
        ("settings", settings::panel_ids()),
        ("labs", labs::panel_ids()),
    ];
    for (dom, ids) in groups {
        for &pid in ids {
            // Skip paths already registered as top-level domain roots
            let path = canonical_panel_path(pid);
            if matches!(path.as_str(), "/agents" | "/labs" | "/chat") {
                continue;
            }
            let handler = move |State(state): State<AppState>| async move {
                let (tpl, all_ids) = domain_template(dom);
                let html = finalize_v4_html(
                    tpl,
                    dom,
                    pid,
                    &state.operator_url,
                    json!({
                        "panels": all_ids,
                        "isolatedSandbox": dom == "labs",
                        "overlaySupported": dom == "settings"
                    }),
                );
                html_response(html)
            };
            router = router.route(&path, get(handler));

            // Also support flat aliases for settings-* and lab sub-panels so direct links work cleanly
            if pid.starts_with("settings-") || (dom == "labs" && pid != "labs") {
                let flat = format!("/{pid}");
                if flat != path {
                    let flat_handler = move |State(state): State<AppState>| async move {
                        let (tpl, all_ids) = domain_template(dom);
                        let html = finalize_v4_html(
                            tpl,
                            dom,
                            pid,
                            &state.operator_url,
                            json!({
                                "panels": all_ids,
                                "isolatedSandbox": dom == "labs",
                                "overlaySupported": dom == "settings"
                            }),
                        );
                        html_response(html)
                    };
                    router = router.route(&flat, get(flat_handler));
                }
            }
        }
    }
    router
}

pub fn router() -> Router<AppState> {
    let base = Router::new()
        .merge(overview::router())
        .merge(operations::router())
        .merge(agents::router())
        .merge(governance::router())
        .merge(evidence::router())
        .merge(settings::router())
        .merge(labs::router())
        .merge(chat::router())
        .merge(components::router());
    register_clean_panel_routes(base)
}

pub fn all_panel_ids() -> Vec<&'static str> {
    let mut ids = Vec::with_capacity(65);
    ids.extend_from_slice(overview::panel_ids());
    ids.extend_from_slice(operations::panel_ids());
    ids.extend_from_slice(agents::panel_ids());
    ids.extend_from_slice(governance::panel_ids());
    ids.extend_from_slice(evidence::panel_ids());
    ids.extend_from_slice(settings::panel_ids());
    ids.extend_from_slice(labs::panel_ids());
    ids.extend_from_slice(chat::panel_ids());
    ids
}

pub fn domain_manifest() -> Vec<Value> {
    vec![
        json!({ "id": "overview", "route": "/overview", "panels": overview::panel_ids() }),
        json!({ "id": "operations", "route": "/operations", "panels": operations::panel_ids() }),
        json!({ "id": "agents", "route": "/agents", "panels": agents::panel_ids() }),
        json!({ "id": "governance", "route": "/governance", "panels": governance::panel_ids() }),
        json!({ "id": "evidence", "route": "/evidence", "panels": evidence::panel_ids() }),
        json!({ "id": "settings", "route": "/settings", "panels": settings::panel_ids() }),
        json!({ "id": "labs", "route": "/labs", "panels": labs::panel_ids() }),
        json!({ "id": "chat", "route": "/chat", "panels": chat::panel_ids() }),
    ]
}
