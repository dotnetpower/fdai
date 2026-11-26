//! Shared HTML rendering utilities for FDAI Console v4 Pure-Rust pages.

use axum::{
    http::{header, StatusCode},
    response::{Html, IntoResponse, Response},
};
use serde_json::{json, Value};

/// Maps a canonical FDAI Console v4 panel ID to its unique domain-scoped HTTP path (zero `#tab=`).
pub fn canonical_panel_path(panel_id: &str) -> String {
    match panel_id {
        "command-deck-chat" => "/chat".to_string(),
        "agents" => "/agents".to_string(),
        "labs" => "/labs".to_string(),
        "dashboard"
        | "dashboard-v2"
        | "operating-outcomes"
        | "control-assurance"
        | "verticals"
        | "cost-governance"
        | "llm-cost" => format!("/overview/{panel_id}"),
        "live"
        | "gpu"
        | "incidents"
        | "code-security"
        | "vulnerability-risk"
        | "configuration-baselines"
        | "hil-queue"
        | "alert-quality"
        | "detection-readiness"
        | "conversation-delivery"
        | "workflow-apps"
        | "automation-blueprints"
        | "processes"
        | "scheduler-runs"
        | "background-tasks"
        | "scheduled-continuations"
        | "provision"
        | "onboarding" => format!("/operations/{panel_id}"),
        "pantheon" | "handover" | "agent-activity" | "skills" | "capabilities" => {
            format!("/agents/{panel_id}")
        }
        "rules"
        | "trust-routing"
        | "ontology"
        | "scope"
        | "architecture"
        | "blast-radius"
        | "promotion-gates"
        | "workflow-builder"
        | "knowledge"
        | "github"
        | "gitlab"
        | "azure-devops"
        | "documents" => format!("/governance/{panel_id}"),
        "audit"
        | "trace"
        | "rca"
        | "browser-evidence"
        | "conversation-search"
        | "reports" => format!("/evidence/{panel_id}"),
        "aks-commerce"
        | "assurance-twin"
        | "forecast-learning"
        | "conversation-assurance"
        | "context-selection-comparisons" => format!("/labs/{panel_id}"),
        id if id.starts_with("settings-") => {
            format!("/settings/{}", id.trim_start_matches("settings-"))
        }
        id => format!("/{id}"),
    }
}

/// Rewrites `/domain#tab=<panel>` occurrences to unique clean paths `/<panel>`.
fn rewrite_hash_tab_links(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    let prefixes = [
        "/overview#tab=",
        "/operations#tab=",
        "/agents#tab=",
        "/governance#tab=",
        "/evidence#tab=",
        "/settings#tab=",
        "/labs#tab=",
    ];
    let mut rest = input;
    while !rest.is_empty() {
        let mut best: Option<(usize, usize)> = None;
        for p in prefixes {
            if let Some(idx) = rest.find(p) {
                match best {
                    None => best = Some((idx, p.len())),
                    Some((bi, _)) if idx < bi => best = Some((idx, p.len())),
                    _ => {}
                }
            }
        }
        let Some((pos, plen)) = best else {
            out.push_str(rest);
            break;
        };
        out.push_str(&rest[..pos]);
        let after = &rest[pos + plen..];
        let id_len = after
            .bytes()
            .take_while(|b| b.is_ascii_alphanumeric() || *b == b'-')
            .count();
        if id_len > 0 {
            let pid = &after[..id_len];
            out.push_str(&canonical_panel_path(pid));
            rest = &after[id_len..];
        } else {
            out.push_str(&rest[pos..pos + plen]);
            rest = after;
        }
    }
    out
}

/// Rewrites any remaining mockup HTML relative links to canonical Pure-Rust Axum routes
/// and injects the v4 runtime bootstrap script before `</body>`.
pub fn finalize_v4_html(
    raw_html: &str,
    domain: &str,
    default_panel: &str,
    operator_url: &str,
    extra_bootstrap: Value,
) -> String {
    let base_rewritten = raw_html
        .replace("href=\"fdai-console-shared.css\"", "href=\"/assets/fdai-console-shared.css\"")
        .replace("src=\"fdai-console-shell.js\"", "src=\"/assets/fdai-console-shell.js\"")
        .replace("mockup-overview.html", "/overview")
        .replace("mockup-operations.html", "/operations")
        .replace("mockup-agents.html", "/agents")
        .replace("mockup-governance.html", "/governance")
        .replace("mockup-evidence.html", "/evidence")
        .replace("mockup-settings-labs.html#tab=labs", "/labs")
        .replace("mockup-settings-labs.html#tab=aks-commerce", "/labs/aks-commerce")
        .replace("mockup-settings-labs.html#tab=assurance-twin", "/labs/assurance-twin")
        .replace("mockup-settings-labs.html#tab=forecast-learning", "/labs/forecast-learning")
        .replace(
            "mockup-settings-labs.html#tab=conversation-assurance",
            "/labs/conversation-assurance",
        )
        .replace(
            "mockup-settings-labs.html#tab=context-selection-comparisons",
            "/labs/context-selection-comparisons",
        )
        .replace("mockup-settings-labs.html", "/settings")
        .replace("mockup-chat.html", "/chat")
        .replace("overview-components.html", "/components")
        .replace("overview-amethyst-teal.html", "/overview/dashboard");
    let rewritten = rewrite_hash_tab_links(&base_rewritten);

    let bootstrap_obj = json!({
        "engine": "pure-rust-axum",
        "version": "v4",
        "domain": domain,
        "defaultPanel": default_panel,
        "canonicalPath": canonical_panel_path(default_panel),
        "operatorUrl": operator_url,
        "extra": extra_bootstrap
    });
    let safe_json = bootstrap_obj
        .to_string()
        .replace("</", "<\\/")
        .replace("<!--", "<\\!--");
    let inject = format!(
        "<script>window.__FDAI_V4_BOOTSTRAP__={safe_json};</script>\n<script defer src=\"/assets/fdai-console-live.js\"></script>\n</body>"
    );

    if let Some(pos) = rewritten.rfind("</body>") {
        let mut out = String::with_capacity(rewritten.len() + inject.len());
        out.push_str(&rewritten[..pos]);
        out.push_str(&inject);
        out.push_str(&rewritten[pos + "</body>".len()..]);
        out
    } else {
        let mut out = rewritten;
        out.push_str(&inject);
        out
    }
}

pub fn html_response(body: String) -> Response {
    (
        StatusCode::OK,
        [
            (header::CACHE_CONTROL, "no-store"),
            (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
            (header::X_FRAME_OPTIONS, "SAMEORIGIN"),
            (header::REFERRER_POLICY, "strict-origin-when-cross-origin"),
        ],
        Html(body),
    )
        .into_response()
}
