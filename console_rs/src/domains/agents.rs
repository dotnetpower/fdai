//! Domain 3: 에이전트 (`agents`, 6 panels).
//! Owned by the `agents` domain stream.
//! Pure-Rust + Axum 0.8 endpoints with upstream-locked 15-agent Pantheon metadata,
//! safe `not-measured` fallback semantics, and native SSE streaming.

use axum::{
    extract::{Path as AxumPath, Query, State},
    http::{header, HeaderMap, HeaderName, StatusCode},
    response::{
        sse::{Event, KeepAlive, Sse},
        IntoResponse, Response,
    },
    routing::get,
    Json, Router,
};
use futures_util::stream::{self, Stream, StreamExt};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    convert::Infallible,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use crate::{
    repos,
    shell::{finalize_v4_html, html_response},
    AppState, SseLeaseDropGuard,
};

const TEMPLATE: &str = include_str!("../../templates/agents.html");

const PANELS: [&str; 6] = [
    "agents",
    "pantheon",
    "handover",
    "agent-activity",
    "skills",
    "capabilities",
];

const LIFECYCLE_PHASES: [&str; 6] = [
    "ingest",
    "evidence",
    "judgment",
    "approval",
    "execution",
    "audit",
];

const CAPABILITY_FIVE_STATES: [&str; 5] = [
    "declared",
    "runtime",
    "binding",
    "role",
    "execution",
];

const MAX_AUTH_HEADER_LEN: usize = 4096;
const MAX_SSE_HEARTBEATS: u64 = 240;
const SSE_POLL_BASE_SECS: u64 = 15;
const SSE_POLL_BACKOFF_SECS: u64 = 30;
const X_ACCEL_BUFFERING: HeaderName = HeaderName::from_static("x-accel-buffering");

#[derive(Debug, Clone, Copy, Serialize)]
pub struct PantheonAgentMeta {
    pub name: &'static str,
    pub slug: &'static str,
    pub icon: &'static str,
    pub role_en: &'static str,
    pub role_ko: &'static str,
    pub layer: &'static str,
    pub branch: &'static str,
    pub reports_to: Option<&'static str>,
    pub hard_dependency: bool,
    pub hot_path_llm: bool,
    pub accept_autonomous_upstream: bool,
    pub owns: &'static [&'static str],
}

/// Fixed upstream-locked 15-agent Pantheon metadata aligned with `PANTHEON_SPECS`,
/// `console/public/agent-icons/manifest.json`, and `config/agent-stewardship.yaml`.
pub const PANTHEON_CATALOG: [PantheonAgentMeta; 15] = [
    PantheonAgentMeta {
        name: "Odin",
        slug: "odin",
        icon: "/agent-icons/odin.svg",
        role_en: "Master Planner",
        role_ko: "총괄 조정자",
        layer: "governance",
        branch: "root",
        reports_to: None,
        hard_dependency: false,
        hot_path_llm: false,
        accept_autonomous_upstream: false,
        owns: &["ArbitrationDecision"],
    },
    PantheonAgentMeta {
        name: "Thor",
        slug: "thor",
        icon: "/agent-icons/thor.svg",
        role_en: "Responder",
        role_ko: "격리 실행기",
        layer: "pipeline",
        branch: "thor",
        reports_to: Some("Odin"),
        hard_dependency: false,
        hot_path_llm: false,
        accept_autonomous_upstream: false,
        owns: &["ActionRun"],
    },
    PantheonAgentMeta {
        name: "Forseti",
        slug: "forseti",
        icon: "/agent-icons/forseti.svg",
        role_en: "Judge",
        role_ko: "정책 · 위험 판정",
        layer: "pipeline",
        branch: "forseti",
        reports_to: Some("Odin"),
        hard_dependency: false,
        hot_path_llm: true,
        accept_autonomous_upstream: false,
        owns: &[
            "Verdict",
            "SecurityEvent",
            "ArbitrationRequest",
            "ProspectiveLineage",
        ],
    },
    PantheonAgentMeta {
        name: "Huginn",
        slug: "huginn",
        icon: "/agent-icons/huginn.svg",
        role_en: "Event Collector",
        role_ko: "원천 이벤트 수집기",
        layer: "pipeline",
        branch: "forseti",
        reports_to: Some("Forseti"),
        hard_dependency: false,
        hot_path_llm: false,
        accept_autonomous_upstream: false,
        owns: &["Event", "Change"],
    },
    PantheonAgentMeta {
        name: "Heimdall",
        slug: "heimdall",
        icon: "/agent-icons/heimdall.svg",
        role_en: "Observer",
        role_ko: "관측 · 이상 감지",
        layer: "pipeline",
        branch: "forseti",
        reports_to: Some("Forseti"),
        hard_dependency: false,
        hot_path_llm: false,
        accept_autonomous_upstream: false,
        owns: &[
            "Anomaly",
            "Drift",
            "Forecast",
            "ForecastOutcome",
            "RetrievalValidation",
            "EvidenceConflict",
            "RecoveryEffectObservation",
        ],
    },
    PantheonAgentMeta {
        name: "Vidar",
        slug: "vidar",
        icon: "/agent-icons/vidar.svg",
        role_en: "Recovery",
        role_ko: "복구 · 독립 효과 검증",
        layer: "pipeline",
        branch: "thor",
        reports_to: Some("Thor"),
        hard_dependency: true,
        hot_path_llm: false,
        accept_autonomous_upstream: false,
        owns: &["Rollback"],
    },
    PantheonAgentMeta {
        name: "Var",
        slug: "var",
        icon: "/agent-icons/var.svg",
        role_en: "Approver",
        role_ko: "승인 요청 중재",
        layer: "pipeline",
        branch: "thor",
        reports_to: Some("Thor"),
        hard_dependency: false,
        hot_path_llm: false,
        accept_autonomous_upstream: false,
        owns: &["Approval"],
    },
    PantheonAgentMeta {
        name: "Bragi",
        slug: "bragi",
        icon: "/agent-icons/bragi.svg",
        role_en: "Narrator",
        role_ko: "운영자 대화 서술",
        layer: "pipeline",
        branch: "thor",
        reports_to: Some("Thor"),
        hard_dependency: false,
        hot_path_llm: true,
        accept_autonomous_upstream: false,
        owns: &[
            "Conversation",
            "Turn",
            "UserPreference",
            "HandoffEscalation",
            "PostTurnReview",
        ],
    },
    PantheonAgentMeta {
        name: "Saga",
        slug: "saga",
        icon: "/agent-icons/saga.svg",
        role_en: "Auditor",
        role_ko: "2단계 감사 원장",
        layer: "governance",
        branch: "staff",
        reports_to: Some("Odin"),
        hard_dependency: true,
        hot_path_llm: false,
        accept_autonomous_upstream: false,
        owns: &["AuditEntry", "Issue"],
    },
    PantheonAgentMeta {
        name: "Mimir",
        slug: "mimir",
        icon: "/agent-icons/mimir.svg",
        role_en: "Rule Steward",
        role_ko: "규칙 · 정책 관리자",
        layer: "governance",
        branch: "staff",
        reports_to: Some("Odin"),
        hard_dependency: false,
        hot_path_llm: false,
        accept_autonomous_upstream: false,
        owns: &[
            "Rule",
            "Policy",
            "PolicyActivationRequest",
            "RuleGenerationBuildRequest",
            "RuleGenerationBuildResult",
        ],
    },
    PantheonAgentMeta {
        name: "Muninn",
        slug: "muninn",
        icon: "/agent-icons/muninn.svg",
        role_en: "Memory",
        role_ko: "기억 · 컨텍스트 저장",
        layer: "governance",
        branch: "staff",
        reports_to: Some("Odin"),
        hard_dependency: false,
        hot_path_llm: false,
        accept_autonomous_upstream: false,
        owns: &["StateSnapshot", "ContextIndex"],
    },
    PantheonAgentMeta {
        name: "Norns",
        slug: "norns",
        icon: "/agent-icons/norns.svg",
        role_en: "Learner",
        role_ko: "이력 회고 · 규칙 제안",
        layer: "governance",
        branch: "staff",
        reports_to: Some("Odin"),
        hard_dependency: false,
        hot_path_llm: false,
        accept_autonomous_upstream: false,
        owns: &["RuleCandidate", "Pattern"],
    },
    PantheonAgentMeta {
        name: "Njord",
        slug: "njord",
        icon: "/agent-icons/njord.svg",
        role_en: "Cost",
        role_ko: "비용 거버넌스 자문",
        layer: "domain",
        branch: "forseti",
        reports_to: Some("Forseti"),
        hard_dependency: false,
        hot_path_llm: false,
        accept_autonomous_upstream: false,
        owns: &["CostAnomaly"],
    },
    PantheonAgentMeta {
        name: "Freyr",
        slug: "freyr",
        icon: "/agent-icons/freyr.svg",
        role_en: "Capacity",
        role_ko: "사전 용량 예측",
        layer: "domain",
        branch: "forseti",
        reports_to: Some("Forseti"),
        hard_dependency: false,
        hot_path_llm: false,
        accept_autonomous_upstream: false,
        owns: &["CapacityForecast", "CapacityGraduationRecommendation"],
    },
    PantheonAgentMeta {
        name: "Loki",
        slug: "loki",
        icon: "/agent-icons/loki.svg",
        role_en: "Chaos",
        role_ko: "카오스 복원력 검증",
        layer: "domain",
        branch: "forseti",
        reports_to: Some("Forseti"),
        hard_dependency: false,
        hot_path_llm: false,
        accept_autonomous_upstream: true,
        owns: &["ChaosExperiment", "ResilienceScore"],
    },
];

#[derive(Debug, Default, Deserialize)]
struct ActivityQuery {
    agent: Option<String>,
    correlation_id: Option<String>,
    limit: Option<u16>,
}

pub fn panel_ids() -> &'static [&'static str] {
    &PANELS
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/agents", get(page_agents))
        .route("/api/v4/agents/summary", get(api_agents_summary))
        .route("/api/v4/agents/pantheon", get(api_agents_pantheon))
        .route("/api/v4/agents/pantheon/{slug}", get(api_agents_pantheon_one))
        .route("/api/v4/agents/handover", get(api_agents_handover))
        .route("/api/v4/agents/activity", get(api_agents_activity))
        .route("/api/v4/agents/stream", get(api_agents_stream))
        .route("/api/v4/agents/skills", get(api_agents_skills))
        .route("/api/v4/agents/capabilities", get(api_agents_capabilities))
}

fn json_no_store(status: StatusCode, body: Value) -> Response {
    (
        status,
        [
            (header::CACHE_CONTROL, "no-store"),
            (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
        ],
        Json(body),
    )
        .into_response()
}

fn extract_auth(headers: &HeaderMap) -> Option<&str> {
    let raw = headers
        .get(header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())?;
    let trimmed = raw.trim();
    if trimmed.is_empty()
        || trimmed.len() > MAX_AUTH_HEADER_LEN
        || trimmed.chars().any(char::is_control)
    {
        return None;
    }
    Some(trimmed)
}

fn canonical_pantheon_agent(raw: &str) -> Option<&'static PantheonAgentMeta> {
    let clean = raw.trim();
    if clean.is_empty() {
        return None;
    }
    PANTHEON_CATALOG.iter().find(|agent| {
        agent.name.eq_ignore_ascii_case(clean) || agent.slug.eq_ignore_ascii_case(clean)
    })
}

fn canonical_pantheon_name(raw: &str) -> Option<&'static str> {
    canonical_pantheon_agent(raw).map(|agent| agent.name)
}

fn sanitize_query_token(raw: &str) -> String {
    raw.trim()
        .chars()
        .filter(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_' | '.' | ':'))
        .take(64)
        .collect()
}

fn unix_epoch_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

fn pantheon_invariants() -> Value {
    let hard_deps: Vec<&str> = PANTHEON_CATALOG
        .iter()
        .filter(|a| a.hard_dependency)
        .map(|a| a.name)
        .collect();
    let hot_path_llm: Vec<&str> = PANTHEON_CATALOG
        .iter()
        .filter(|a| a.hot_path_llm)
        .map(|a| a.name)
        .collect();
    let owned_object_count: usize = PANTHEON_CATALOG.iter().map(|a| a.owns.len()).sum();
    json!({
        "pantheon_count": PANTHEON_CATALOG.len(),
        "owned_object_count": owned_object_count,
        "single_writer_verified": true,
        "authority_separation": "Var (Approver) != Thor (Executor)",
        "bus_only": true,
        "direct_agent_calls_forbidden": true,
        "hard_dependency_agents": hard_deps,
        "llm_hot_path_allowlist": hot_path_llm
    })
}

fn org_tree_snapshot() -> Value {
    let forseti_branch: Vec<&str> = PANTHEON_CATALOG
        .iter()
        .filter(|a| a.branch == "forseti")
        .map(|a| a.name)
        .collect();
    let thor_branch: Vec<&str> = PANTHEON_CATALOG
        .iter()
        .filter(|a| a.branch == "thor")
        .map(|a| a.name)
        .collect();
    let staff_branch: Vec<&str> = PANTHEON_CATALOG
        .iter()
        .filter(|a| a.branch == "staff")
        .map(|a| a.name)
        .collect();
    json!({
        "root": "Odin",
        "branches": [
            {
                "id": "forseti",
                "manager": "Forseti",
                "label": "관측 · 판정 · 전문",
                "count": forseti_branch.len(),
                "members": forseti_branch
            },
            {
                "id": "thor",
                "manager": "Thor",
                "label": "승인 · 실행 · 복구 · 대화",
                "count": thor_branch.len(),
                "members": thor_branch
            },
            {
                "id": "staff",
                "manager": "Odin",
                "label": "Odin 직속 스태프 (규칙 · 기억 · 감사 · 학습)",
                "count": staff_branch.len(),
                "members": staff_branch
            }
        ]
    })
}

async fn page_agents(State(state): State<AppState>) -> Response {
    let html = finalize_v4_html(
        TEMPLATE,
        "agents",
        "agents",
        &state.operator_url,
        json!({
            "panels": PANELS,
            "pantheonCount": PANTHEON_CATALOG.len(),
            "sseStream": "/api/v4/agents/stream",
            "endpoints": {
                "summary": "/api/v4/agents/summary",
                "pantheon": "/api/v4/agents/pantheon",
                "handover": "/api/v4/agents/handover",
                "activity": "/api/v4/agents/activity",
                "skills": "/api/v4/agents/skills",
                "capabilities": "/api/v4/agents/capabilities"
            }
        }),
    );
    html_response(html)
}

fn is_db_measured(val: &Value) -> bool {
    val.get("measurement_status")
        .and_then(Value::as_str)
        .is_some_and(|s| s == "measured")
}

async fn api_agents_summary(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = extract_auth(&headers);
    let up = state.upstream.get_json("/agents/activity", auth).await;
    if up.reachable && up.status == 200 {
        if let Some(payload) = up.payload {
            return json_no_store(
                StatusCode::OK,
                json!({
                    "source": "operator-service",
                    "domain": "agents",
                    "panel": "agents",
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "read_only_surface": true,
                    "grants_execution_authority": false,
                    "observed_at_unix": unix_epoch_secs(),
                    "invariants": pantheon_invariants(),
                    "catalog": PANTHEON_CATALOG,
                    "data": payload
                }),
            );
        }
    }

    if state.db.is_configured() {
        let db_val = repos::agents::fetch_actor_summary(&state.db).await;
        if is_db_measured(&db_val) {
            return json_no_store(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "agents",
                    "panel": "agents",
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "read_only_surface": true,
                    "grants_execution_authority": false,
                    "observed_at_unix": unix_epoch_secs(),
                    "invariants": pantheon_invariants(),
                    "catalog": PANTHEON_CATALOG,
                    "data": db_val
                }),
            );
        }
    }

    let reason = if !up.reachable {
        "operator-service offline"
    } else if up.status == 401 || up.status == 403 {
        "operator-service unauthenticated or unauthorized"
    } else {
        "operator-service activity unavailable"
    };
    let mut env = state
        .upstream
        .not_measured_envelope("agents", "/agents/activity", reason);
    if let Some(obj) = env.as_object_mut() {
        obj.insert("panel".to_string(), json!("agents"));
        obj.insert("measurement_status".to_string(), json!("not-measured"));
        obj.insert("read_only_surface".to_string(), json!(true));
        obj.insert("grants_execution_authority".to_string(), json!(false));
        obj.insert("observed_at_unix".to_string(), json!(unix_epoch_secs()));
        obj.insert("upstream_status".to_string(), json!(up.status));
        obj.insert("live_counts".to_string(), Value::Null);
        obj.insert("invariants".to_string(), pantheon_invariants());
        obj.insert("catalog".to_string(), json!(PANTHEON_CATALOG));
    }
    json_no_store(StatusCode::OK, env)
}

async fn api_agents_pantheon(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = extract_auth(&headers);
    let up = state.upstream.get_json("/agents/activity", auth).await;
    if up.reachable && up.status == 200 {
        if let Some(payload) = up.payload {
            return json_no_store(
                StatusCode::OK,
                json!({
                    "source": "operator-service",
                    "domain": "agents",
                    "panel": "pantheon",
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "read_only": true,
                    "read_only_surface": true,
                    "grants_execution_authority": false,
                    "observed_at_unix": unix_epoch_secs(),
                    "upstream_url": state.operator_url,
                    "upstream_status": up.status,
                    "invariants": pantheon_invariants(),
                    "org_tree": org_tree_snapshot(),
                    "agents": PANTHEON_CATALOG,
                    "live_activity": payload
                }),
            );
        }
    }

    if state.db.is_configured() {
        let db_val = repos::agents::fetch_actor_summary(&state.db).await;
        if is_db_measured(&db_val) {
            return json_no_store(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "agents",
                    "panel": "pantheon",
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "read_only": true,
                    "read_only_surface": true,
                    "grants_execution_authority": false,
                    "observed_at_unix": unix_epoch_secs(),
                    "upstream_url": state.operator_url,
                    "upstream_status": up.status,
                    "invariants": pantheon_invariants(),
                    "org_tree": org_tree_snapshot(),
                    "agents": PANTHEON_CATALOG,
                    "live_activity": db_val
                }),
            );
        }
    }

    json_no_store(
        StatusCode::OK,
        json!({
            "source": "console-v4-rust",
            "domain": "agents",
            "panel": "pantheon",
            "measurement_state": "not-measured",
            "measurement_status": "not-measured",
            "read_only": true,
            "read_only_surface": true,
            "grants_execution_authority": false,
            "observed_at_unix": unix_epoch_secs(),
            "upstream_url": state.operator_url,
            "upstream_status": up.status,
            "invariants": pantheon_invariants(),
            "org_tree": org_tree_snapshot(),
            "agents": PANTHEON_CATALOG,
            "live_activity": Value::Null
        }),
    )
}

async fn api_agents_pantheon_one(
    State(state): State<AppState>,
    AxumPath(slug): AxumPath<String>,
    headers: HeaderMap,
) -> Response {
    let Some(agent) = canonical_pantheon_agent(&slug) else {
        return json_no_store(
            StatusCode::NOT_FOUND,
            json!({
                "domain": "agents",
                "panel": "pantheon",
                "error": "unknown_pantheon_agent",
                "read_only_surface": true,
                "grants_execution_authority": false,
                "observed_at_unix": unix_epoch_secs(),
                "message": "requested agent is not in the fixed 15-agent pantheon"
            }),
        );
    };
    let auth = extract_auth(&headers);
    let upstream_path = format!("/agents/activity?agent={}&limit=20", agent.name);
    let up = state.upstream.get_json(&upstream_path, auth).await;
    let direct_reports: Vec<&str> = PANTHEON_CATALOG
        .iter()
        .filter(|candidate| candidate.reports_to == Some(agent.name))
        .map(|candidate| candidate.name)
        .collect();

    if up.reachable && up.status == 200 {
        if let Some(payload) = up.payload {
            return json_no_store(
                StatusCode::OK,
                json!({
                    "source": "operator-service",
                    "domain": "agents",
                    "panel": "pantheon",
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "read_only": true,
                    "read_only_surface": true,
                    "grants_execution_authority": false,
                    "observed_at_unix": unix_epoch_secs(),
                    "upstream_status": up.status,
                    "agent": agent,
                    "direct_reports": direct_reports,
                    "live_activity": payload
                }),
            );
        }
    }

    if state.db.is_configured() {
        let db_val = repos::agents::fetch_agent_detail(&state.db, agent.name, Some(20)).await;
        if is_db_measured(&db_val) {
            return json_no_store(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "agents",
                    "panel": "pantheon",
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "read_only": true,
                    "read_only_surface": true,
                    "grants_execution_authority": false,
                    "observed_at_unix": unix_epoch_secs(),
                    "upstream_status": up.status,
                    "agent": agent,
                    "direct_reports": direct_reports,
                    "live_activity": db_val
                }),
            );
        }
    }

    json_no_store(
        StatusCode::OK,
        json!({
            "source": "console-v4-rust",
            "domain": "agents",
            "panel": "pantheon",
            "measurement_state": "not-measured",
            "measurement_status": "not-measured",
            "read_only": true,
            "read_only_surface": true,
            "grants_execution_authority": false,
            "observed_at_unix": unix_epoch_secs(),
            "upstream_status": up.status,
            "agent": agent,
            "direct_reports": direct_reports,
            "live_activity": Value::Null
        }),
    )
}

async fn api_agents_handover(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = extract_auth(&headers);
    let up = state.upstream.get_json("/stewardship", auth).await;
    let policy = json!({
        "stewardship_version": 1,
        "hop_timeout_seconds": 900,
        "over_assigned_max": 5,
        "accountability_only": true,
        "grants_execution_authority": false,
        "loki_accept_autonomous_upstream": true,
        "loki_reason": "Chaos proposals are always HIL; no standing domain owner upstream."
    });
    let slots: Vec<Value> = PANTHEON_CATALOG
        .iter()
        .map(|a| {
            json!({
                "agent": a.name,
                "slug": a.slug,
                "icon": a.icon,
                "branch": a.branch,
                "accept_autonomous_upstream": a.accept_autonomous_upstream
            })
        })
        .collect();

    if up.reachable && up.status == 200 {
        if let Some(payload) = up.payload {
            return json_no_store(
                StatusCode::OK,
                json!({
                    "source": "operator-service",
                    "domain": "agents",
                    "panel": "handover",
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "read_only_surface": true,
                    "grants_execution_authority": false,
                    "observed_at_unix": unix_epoch_secs(),
                    "policy": policy,
                    "agent_slots": slots,
                    "data": payload
                }),
            );
        }
    }

    if state.db.is_configured() {
        let db_val = repos::agents::fetch_handover_stewardship(&state.db).await;
        if is_db_measured(&db_val) {
            return json_no_store(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "agents",
                    "panel": "handover",
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "read_only_surface": true,
                    "grants_execution_authority": false,
                    "observed_at_unix": unix_epoch_secs(),
                    "policy": policy,
                    "agent_slots": slots,
                    "data": db_val
                }),
            );
        }
    }

    let mut env = state.upstream.not_measured_envelope(
        "agents",
        "/stewardship",
        "stewardship projection unavailable (not-measured; never fabricated as 0)",
    );
    if let Some(obj) = env.as_object_mut() {
        obj.insert("panel".to_string(), json!("handover"));
        obj.insert("measurement_status".to_string(), json!("not-measured"));
        obj.insert("read_only_surface".to_string(), json!(true));
        obj.insert("grants_execution_authority".to_string(), json!(false));
        obj.insert("observed_at_unix".to_string(), json!(unix_epoch_secs()));
        obj.insert("upstream_status".to_string(), json!(up.status));
        obj.insert("policy".to_string(), policy);
        obj.insert("steward_bindings".to_string(), Value::Null);
        obj.insert("agent_slots".to_string(), json!(slots));
    }
    json_no_store(StatusCode::OK, env)
}

async fn api_agents_activity(
    State(state): State<AppState>,
    Query(query): Query<ActivityQuery>,
    headers: HeaderMap,
) -> Response {
    let auth = extract_auth(&headers);
    let limit = query.limit.unwrap_or(50).clamp(1, 500);

    let agent_clean = match query.agent.as_deref().map(str::trim) {
        None | Some("") => None,
        Some(raw) if raw.eq_ignore_ascii_case("all") => None,
        Some(raw) => match canonical_pantheon_name(raw) {
            Some(valid) => Some(valid.to_string()),
            None => {
                return json_no_store(
                    StatusCode::BAD_REQUEST,
                    json!({
                        "domain": "agents",
                        "panel": "agent-activity",
                        "error": "invalid_agent_name",
                        "read_only_surface": true,
                        "grants_execution_authority": false,
                        "observed_at_unix": unix_epoch_secs(),
                        "message": "agent filter must be one of the 15 fixed pantheon agents"
                    }),
                );
            }
        },
    };

    let corr_clean = query
        .correlation_id
        .as_deref()
        .map(sanitize_query_token)
        .filter(|s| !s.is_empty());

    let mut upstream_path = format!("/agents/activity?limit={limit}");
    if let Some(ref ag) = agent_clean {
        upstream_path.push_str("&agent=");
        upstream_path.push_str(ag);
    }
    if let Some(ref cid) = corr_clean {
        upstream_path.push_str("&correlation_id=");
        upstream_path.push_str(cid);
    }

    let filters = json!({
        "agent": agent_clean,
        "correlation_id": corr_clean,
        "limit": limit
    });

    let up = state.upstream.get_json(&upstream_path, auth).await;
    if up.reachable && up.status == 200 {
        if let Some(payload) = up.payload {
            return json_no_store(
                StatusCode::OK,
                json!({
                    "source": "operator-service",
                    "domain": "agents",
                    "panel": "agent-activity",
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "read_only_surface": true,
                    "grants_execution_authority": false,
                    "observed_at_unix": unix_epoch_secs(),
                    "filters": filters,
                    "lifecycle_phases": LIFECYCLE_PHASES,
                    "data": payload
                }),
            );
        }
    }

    if state.db.is_configured() {
        let db_val = repos::agents::fetch_activity(
            &state.db,
            agent_clean.as_deref(),
            corr_clean.as_deref(),
            Some(usize::from(limit)),
        )
        .await;
        if is_db_measured(&db_val) {
            return json_no_store(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "agents",
                    "panel": "agent-activity",
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "read_only_surface": true,
                    "grants_execution_authority": false,
                    "observed_at_unix": unix_epoch_secs(),
                    "filters": filters,
                    "lifecycle_phases": LIFECYCLE_PHASES,
                    "data": db_val
                }),
            );
        }
    }

    let mut env = state.upstream.not_measured_envelope(
        "agents",
        &upstream_path,
        "agent activity stream unavailable (not-measured; never fabricated as 0)",
    );
    if let Some(obj) = env.as_object_mut() {
        obj.insert("panel".to_string(), json!("agent-activity"));
        obj.insert("measurement_status".to_string(), json!("not-measured"));
        obj.insert("read_only_surface".to_string(), json!(true));
        obj.insert("grants_execution_authority".to_string(), json!(false));
        obj.insert("observed_at_unix".to_string(), json!(unix_epoch_secs()));
        obj.insert("upstream_status".to_string(), json!(up.status));
        obj.insert("filters".to_string(), filters);
        obj.insert("lifecycle_phases".to_string(), json!(LIFECYCLE_PHASES));
        obj.insert("trajectories".to_string(), Value::Null);
        obj.insert("events".to_string(), Value::Null);
        obj.insert("heatmap".to_string(), Value::Null);
    }
    json_no_store(StatusCode::OK, env)
}

async fn resolve_stream_probe(state: &AppState, auth: Option<&str>) -> (&'static str, bool, u16, Value) {
    let up = state.upstream.get_json("/agents/activity", auth).await;
    if up.reachable && up.status == 200 {
        if let Some(payload) = up.payload {
            return ("operator-service", true, up.status, payload);
        }
    }
    if state.db.is_configured() {
        let db_snap = repos::agents::fetch_stream_snapshot(&state.db).await;
        if is_db_measured(&db_snap) {
            return ("postgres-direct", true, up.status, db_snap);
        }
    }
    ("console-v4-rust", false, up.status, Value::Null)
}

async fn api_agents_stream(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> (
    [(HeaderName, &'static str); 3],
    Sse<impl Stream<Item = Result<Event, Infallible>>>,
) {
    let lease = SseLeaseDropGuard::acquire(state.active_sse.clone());
    let auth = extract_auth(&headers).map(str::to_string);
    let (source, measured, upstream_status, active_payload) =
        resolve_stream_probe(&state, auth.as_deref()).await;
    let initial_payload = json!({
        "event": "agents-snapshot",
        "domain": "agents",
        "source": source,
        "measurement_state": if measured { "measured" } else { "not-measured" },
        "measurement_status": if measured { "measured" } else { "not-measured" },
        "read_only_surface": true,
        "grants_execution_authority": false,
        "observed_at_unix": unix_epoch_secs(),
        "pantheon_count": PANTHEON_CATALOG.len(),
        "max_heartbeats": MAX_SSE_HEARTBEATS,
        "upstream_reachable": source == "operator-service",
        "upstream_status": upstream_status,
        "active_agents": active_payload
    });
    let initial_event = Event::default()
        .event("agents-snapshot")
        .data(initial_payload.to_string());

    let initial_misses: u32 = if measured { 0 } else { 1 };
    let heartbeat = stream::unfold(
        (state, auth, 1_u64, initial_misses, lease),
        |(st, auth_hdr, seq, misses, guard)| async move {
            if seq > MAX_SSE_HEARTBEATS {
                drop(guard);
                return None;
            }
            let wait_secs = if misses >= 2 {
                SSE_POLL_BACKOFF_SECS
            } else {
                SSE_POLL_BASE_SECS
            };
            tokio::time::sleep(Duration::from_secs(wait_secs)).await;
            if seq == MAX_SSE_HEARTBEATS {
                let end_body = json!({
                    "event": "agents-stream-end",
                    "seq": seq,
                    "domain": "agents",
                    "reason": "max_heartbeats_reached",
                    "observed_at_unix": unix_epoch_secs()
                });
                let ev = Event::default()
                    .event("agents-stream-end")
                    .data(end_body.to_string());
                return Some((
                    Ok::<Event, Infallible>(ev),
                    (st, auth_hdr, seq.saturating_add(1), misses, guard),
                ));
            }
            let (probe_src, ok, probe_status, probe_payload) =
                resolve_stream_probe(&st, auth_hdr.as_deref()).await;
            let next_misses = if ok { 0 } else { misses.saturating_add(1) };
            let body = json!({
                "event": "agents-heartbeat",
                "seq": seq,
                "domain": "agents",
                "source": probe_src,
                "measurement_state": if ok { "measured" } else { "not-measured" },
                "measurement_status": if ok { "measured" } else { "not-measured" },
                "read_only_surface": true,
                "grants_execution_authority": false,
                "observed_at_unix": unix_epoch_secs(),
                "pantheon_count": PANTHEON_CATALOG.len(),
                "upstream_reachable": probe_src == "operator-service",
                "upstream_status": probe_status,
                "active_agents": probe_payload
            });
            let ev = Event::default()
                .event("agents-heartbeat")
                .data(body.to_string());
            Some((
                Ok::<Event, Infallible>(ev),
                (st, auth_hdr, seq.saturating_add(1), next_misses, guard),
            ))
        },
    );

    let combined =
        stream::once(async move { Ok::<Event, Infallible>(initial_event) }).chain(heartbeat);

    let sse = Sse::new(combined).keep_alive(
        KeepAlive::new()
            .interval(Duration::from_secs(SSE_POLL_BASE_SECS))
            .text("keep-alive"),
    );
    (
        [
            (header::CACHE_CONTROL, "no-store"),
            (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
            (X_ACCEL_BUFFERING, "no"),
        ],
        sse,
    )
}

async fn api_agents_skills(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = extract_auth(&headers);
    let up = state.upstream.get_json("/skills", auth).await;
    if up.reachable && up.status == 200 {
        if let Some(payload) = up.payload {
            return json_no_store(
                StatusCode::OK,
                json!({
                    "source": "operator-service",
                    "domain": "agents",
                    "panel": "skills",
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "read_only_boundary": true,
                    "read_only_surface": true,
                    "grants_execution_authority": false,
                    "authority_escalation": "not_applicable",
                    "observed_at_unix": unix_epoch_secs(),
                    "data": payload
                }),
            );
        }
    }

    if state.db.is_configured() {
        let db_val = repos::agents::fetch_skills(&state.db).await;
        if is_db_measured(&db_val) {
            return json_no_store(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "agents",
                    "panel": "skills",
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "read_only_boundary": true,
                    "read_only_surface": true,
                    "grants_execution_authority": false,
                    "authority_escalation": "not_applicable",
                    "observed_at_unix": unix_epoch_secs(),
                    "data": db_val
                }),
            );
        }
    }

    let mut env = state.upstream.not_measured_envelope(
        "agents",
        "/skills",
        "skills catalog projection unavailable (not-measured; never fabricated as 0)",
    );
    if let Some(obj) = env.as_object_mut() {
        obj.insert("panel".to_string(), json!("skills"));
        obj.insert("measurement_status".to_string(), json!("not-measured"));
        obj.insert("read_only_surface".to_string(), json!(true));
        obj.insert("grants_execution_authority".to_string(), json!(false));
        obj.insert("observed_at_unix".to_string(), json!(unix_epoch_secs()));
        obj.insert("upstream_status".to_string(), json!(up.status));
        obj.insert("read_only_boundary".to_string(), json!(true));
        obj.insert("authority_escalation".to_string(), json!("not_applicable"));
        obj.insert("skills".to_string(), Value::Null);
    }
    json_no_store(StatusCode::OK, env)
}

async fn api_agents_capabilities(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = extract_auth(&headers);
    let up = state.upstream.get_json("/capabilities", auth).await;
    if up.reachable && up.status == 200 {
        if let Some(payload) = up.payload {
            return json_no_store(
                StatusCode::OK,
                json!({
                    "source": "operator-service",
                    "domain": "agents",
                    "panel": "capabilities",
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "read_only_surface": true,
                    "five_state_axes": CAPABILITY_FIVE_STATES,
                    "grants_execution_authority": false,
                    "observed_at_unix": unix_epoch_secs(),
                    "data": payload
                }),
            );
        }
    }

    if state.db.is_configured() {
        let db_val = repos::agents::fetch_capabilities(&state.db).await;
        if is_db_measured(&db_val) {
            return json_no_store(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "agents",
                    "panel": "capabilities",
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "read_only_surface": true,
                    "five_state_axes": CAPABILITY_FIVE_STATES,
                    "grants_execution_authority": false,
                    "observed_at_unix": unix_epoch_secs(),
                    "data": db_val
                }),
            );
        }
    }

    let mut env = state.upstream.not_measured_envelope(
        "agents",
        "/capabilities",
        "capabilities catalog projection unavailable (not-measured; never fabricated as 0)",
    );
    if let Some(obj) = env.as_object_mut() {
        obj.insert("panel".to_string(), json!("capabilities"));
        obj.insert("measurement_status".to_string(), json!("not-measured"));
        obj.insert("read_only_surface".to_string(), json!(true));
        obj.insert("observed_at_unix".to_string(), json!(unix_epoch_secs()));
        obj.insert("upstream_status".to_string(), json!(up.status));
        obj.insert("five_state_axes".to_string(), json!(CAPABILITY_FIVE_STATES));
        obj.insert("grants_execution_authority".to_string(), json!(false));
        obj.insert("capabilities".to_string(), Value::Null);
    }
    json_no_store(StatusCode::OK, env)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::build_router;
    use axum::body::Body;
    use axum::http::{header, Request, StatusCode};
    use http_body_util::BodyExt;
    use std::collections::HashSet;
    use std::path::PathBuf;
    use tower::ServiceExt;

    fn offline_state() -> AppState {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."));
        let mut st = AppState::from_repo_root(root, "http://127.0.0.1:1".to_string());
        st.db = crate::db::DbHandle::from_dsn_opt(None, false);
        st
    }

    #[test]
    fn agents_pantheon_catalog_preserves_15_agent_invariants() {
        assert_eq!(panel_ids().len(), 6);
        assert_eq!(PANTHEON_CATALOG.len(), 15);

        let names: HashSet<&str> = PANTHEON_CATALOG.iter().map(|a| a.name).collect();
        assert_eq!(names.len(), 15);

        let roots: Vec<&str> = PANTHEON_CATALOG
            .iter()
            .filter(|a| a.branch == "root")
            .map(|a| a.name)
            .collect();
        assert_eq!(roots, vec!["Odin"]);

        let forseti_count = PANTHEON_CATALOG.iter().filter(|a| a.branch == "forseti").count();
        let thor_count = PANTHEON_CATALOG.iter().filter(|a| a.branch == "thor").count();
        let staff_count = PANTHEON_CATALOG.iter().filter(|a| a.branch == "staff").count();
        assert_eq!((forseti_count, thor_count, staff_count), (6, 4, 4));

        let hard_deps: Vec<&str> = PANTHEON_CATALOG
            .iter()
            .filter(|a| a.hard_dependency)
            .map(|a| a.name)
            .collect();
        assert_eq!(hard_deps, vec!["Vidar", "Saga"]);

        let hot_llm: Vec<&str> = PANTHEON_CATALOG
            .iter()
            .filter(|a| a.hot_path_llm)
            .map(|a| a.name)
            .collect();
        assert_eq!(hot_llm, vec!["Forseti", "Bragi"]);

        // Single-writer invariant: all 38 owned objects have exactly one owning agent
        let mut owned_set: HashSet<&str> = HashSet::new();
        let mut owned_total = 0_usize;
        for agent in PANTHEON_CATALOG {
            for obj in agent.owns {
                owned_total += 1;
                assert!(
                    owned_set.insert(obj),
                    "single-writer violation: duplicate owner for object {obj}"
                );
            }
        }
        assert_eq!(owned_total, 38);
        assert_eq!(owned_set.len(), 38);

        // Authority separation: Var (Approver) != Thor (Executor)
        let var = canonical_pantheon_agent("var");
        let thor = canonical_pantheon_agent("thor");
        assert!(var.is_some() && thor.is_some());
        if let (Some(v), Some(t)) = (var, thor) {
            assert_ne!(v.name, t.name);
            assert_eq!(v.owns, &["Approval"]);
            assert_eq!(t.owns, &["ActionRun"]);
        }

        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."));
        for agent in PANTHEON_CATALOG {
            let icon_file = root
                .join("console/public/agent-icons")
                .join(format!("{}.svg", agent.slug));
            assert!(
                icon_file.exists(),
                "missing official icon for {}: {}",
                agent.name,
                icon_file.display()
            );
        }
    }

    #[tokio::test]
    async fn agents_page_contains_all_6_panels_15_icons_and_zero_legacy_links(
    ) -> Result<(), Box<dyn std::error::Error>> {
        let app = build_router(offline_state());
        let req = Request::builder().uri("/agents").body(Body::empty())?;
        let resp = app.oneshot(req).await?;
        assert_eq!(resp.status(), StatusCode::OK);
        let bytes = resp.into_body().collect().await?.to_bytes();
        let html = String::from_utf8_lossy(&bytes);

        for pid in PANELS {
            let needle = format!("data-panel-id=\"{pid}\"");
            assert!(html.contains(&needle), "missing panel section {needle}");
        }
        for agent in PANTHEON_CATALOG {
            assert!(
                html.contains(agent.icon),
                "missing icon reference {} in /agents HTML",
                agent.icon
            );
        }
        assert!(
            !html.contains("mockup-"),
            "legacy mockup-*.html link must not remain in rendered /agents HTML"
        );
        assert!(html.contains("/api/v4/agents/stream"));
        assert!(html.contains("fdai:live-pulse"));
        assert!(html.contains("agLivePulseBanner"));
        Ok(())
    }

    #[tokio::test]
    async fn agents_all_json_endpoints_return_200_and_not_measured_when_offline(
    ) -> Result<(), Box<dyn std::error::Error>> {
        let state = offline_state();
        let endpoints = [
            "/api/v4/agents/summary",
            "/api/v4/agents/pantheon",
            "/api/v4/agents/handover",
            "/api/v4/agents/activity?agent=Forseti&limit=25",
            "/api/v4/agents/skills",
            "/api/v4/agents/capabilities",
        ];

        for uri in endpoints {
            let app = build_router(state.clone());
            let req = Request::builder().uri(uri).body(Body::empty())?;
            let resp = app.oneshot(req).await?;
            assert_eq!(resp.status(), StatusCode::OK, "non-200 for {uri}");
            assert_eq!(
                resp.headers().get(header::CACHE_CONTROL).and_then(|v| v.to_str().ok()),
                Some("no-store"),
                "missing Cache-Control: no-store on {uri}"
            );
            assert_eq!(
                resp.headers().get(header::X_CONTENT_TYPE_OPTIONS).and_then(|v| v.to_str().ok()),
                Some("nosniff"),
                "missing X-Content-Type-Options: nosniff on {uri}"
            );
            let bytes = resp.into_body().collect().await?.to_bytes();
            let parsed: Value = serde_json::from_slice(&bytes)?;
            assert_eq!(parsed["domain"], json!("agents"), "domain mismatch on {uri}");
            assert_eq!(
                parsed["measurement_state"],
                json!("not-measured"),
                "must report not-measured when upstream is offline on {uri}"
            );
            assert_eq!(parsed["read_only_surface"], json!(true));
            assert_eq!(parsed["grants_execution_authority"], json!(false));
        }
        Ok(())
    }

    #[tokio::test]
    async fn agents_redteam_input_validation_and_single_pantheon_lookup(
    ) -> Result<(), Box<dyn std::error::Error>> {
        let state = offline_state();

        // Invalid agent filter must fail-closed with 400 Bad Request
        let app_bad = build_router(state.clone());
        let req_bad = Request::builder()
            .uri("/api/v4/agents/activity?agent=UnknownEvilAgent")
            .body(Body::empty())?;
        let resp_bad = app_bad.oneshot(req_bad).await?;
        assert_eq!(resp_bad.status(), StatusCode::BAD_REQUEST);
        let bad_json: Value = serde_json::from_slice(&resp_bad.into_body().collect().await?.to_bytes())?;
        assert_eq!(bad_json["error"], json!("invalid_agent_name"));

        // Single agent lookup: known -> 200, unknown -> 404
        let app_ok = build_router(state.clone());
        let req_ok = Request::builder()
            .uri("/api/v4/agents/pantheon/forseti")
            .body(Body::empty())?;
        let resp_ok = app_ok.oneshot(req_ok).await?;
        assert_eq!(resp_ok.status(), StatusCode::OK);
        let ok_json: Value = serde_json::from_slice(&resp_ok.into_body().collect().await?.to_bytes())?;
        assert_eq!(ok_json["agent"]["name"], json!("Forseti"));
        assert_eq!(ok_json["read_only_surface"], json!(true));

        let app_404 = build_router(state);
        let req_404 = Request::builder()
            .uri("/api/v4/agents/pantheon/nonexistent")
            .body(Body::empty())?;
        let resp_404 = app_404.oneshot(req_404).await?;
        assert_eq!(resp_404.status(), StatusCode::NOT_FOUND);
        let nf_json: Value = serde_json::from_slice(&resp_404.into_body().collect().await?.to_bytes())?;
        assert_eq!(nf_json["error"], json!("unknown_pantheon_agent"));

        // Auth header bounds check
        let mut hdrs = HeaderMap::new();
        let oversized = "Bearer ".to_string() + &"a".repeat(MAX_AUTH_HEADER_LEN + 8);
        if let Ok(val) = axum::http::HeaderValue::from_str(&oversized) {
            hdrs.insert(header::AUTHORIZATION, val);
        }
        assert!(extract_auth(&hdrs).is_none());

        Ok(())
    }

    #[tokio::test]
    async fn agents_sse_stream_returns_event_stream_with_initial_snapshot(
    ) -> Result<(), Box<dyn std::error::Error>> {
        let app = build_router(offline_state());
        let req = Request::builder()
            .uri("/api/v4/agents/stream")
            .body(Body::empty())?;
        let resp = app.oneshot(req).await?;
        assert_eq!(resp.status(), StatusCode::OK);
        assert_eq!(
            resp.headers().get(header::CACHE_CONTROL).and_then(|v| v.to_str().ok()),
            Some("no-store")
        );
        assert_eq!(
            resp.headers().get(header::X_CONTENT_TYPE_OPTIONS).and_then(|v| v.to_str().ok()),
            Some("nosniff")
        );
        let ct = resp
            .headers()
            .get(header::CONTENT_TYPE)
            .and_then(|v| v.to_str().ok())
            .unwrap_or("");
        assert!(
            ct.contains("text/event-stream"),
            "expected text/event-stream, got {ct}"
        );
        Ok(())
    }

    #[test]
    fn agents_pantheon_loki_autonomous_upstream_and_attribution_invariants() {
        let autonomous: Vec<&str> = PANTHEON_CATALOG
            .iter()
            .filter(|a| a.accept_autonomous_upstream)
            .map(|a| a.name)
            .collect();
        assert_eq!(autonomous, vec!["Loki"]);

        assert_eq!(
            repos::agents::attribute_pantheon_agent("Saga", "audit.record"),
            Some("Saga")
        );
        assert_eq!(
            repos::agents::attribute_pantheon_agent("fdai.core.control_loop", "risk_gate.unified"),
            Some("Forseti")
        );
        assert_eq!(
            repos::agents::attribute_pantheon_agent("fdai.system", "mimir.rule-source.observed"),
            Some("Mimir")
        );
        assert_eq!(
            repos::agents::attribute_pantheon_agent("fdai.system", "decision-evidence.admission-retained"),
            Some("Muninn")
        );
        assert_eq!(
            repos::agents::attribute_pantheon_agent("fdai.core.hil_resume", "hil.requested"),
            Some("Var")
        );

        let pred = repos::agents::build_agent_where_clause("Forseti");
        assert!(pred.contains("'Forseti'"));
        assert!(pred.contains("'fdai.core.control_loop'"));
    }

    #[tokio::test]
    async fn agents_sse_lease_guard_tracks_active_stream_lifecycle(
    ) -> Result<(), Box<dyn std::error::Error>> {
        use std::sync::atomic::Ordering;
        let state = offline_state();
        assert_eq!(state.active_sse.load(Ordering::SeqCst), 0);

        let app = build_router(state.clone());
        let req = Request::builder()
            .uri("/api/v4/agents/stream")
            .body(Body::empty())?;
        let resp = app.oneshot(req).await?;
        assert_eq!(resp.status(), StatusCode::OK);
        assert_eq!(state.active_sse.load(Ordering::SeqCst), 1);

        drop(resp);
        assert_eq!(state.active_sse.load(Ordering::SeqCst), 0);
        Ok(())
    }

    #[tokio::test]
    async fn agents_postgres_direct_fallback_when_local_db_reachable(
    ) -> Result<(), Box<dyn std::error::Error>> {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."));
        let state = AppState::from_repo_root_with_local_db(root, "http://127.0.0.1:1".to_string());
        if !state.db.is_configured() {
            return Ok(());
        }
        // Probe once; skip only when local PostgreSQL daemon is not running in this environment.
        let probe = repos::agents::fetch_actor_summary(&state.db).await;
        if !is_db_measured(&probe) {
            return Ok(());
        }

        let endpoints = [
            "/api/v4/agents/summary",
            "/api/v4/agents/pantheon",
            "/api/v4/agents/pantheon/forseti",
            "/api/v4/agents/pantheon/loki",
            "/api/v4/agents/handover",
            "/api/v4/agents/activity?agent=Forseti&limit=15",
            "/api/v4/agents/skills",
            "/api/v4/agents/capabilities",
        ];
        for uri in endpoints {
            let app = build_router(state.clone());
            let req = Request::builder().uri(uri).body(Body::empty())?;
            let resp = app.oneshot(req).await?;
            assert_eq!(resp.status(), StatusCode::OK, "non-200 for {uri}");
            let bytes = resp.into_body().collect().await?.to_bytes();
            let parsed: Value = serde_json::from_slice(&bytes)?;
            assert_eq!(
                parsed["measurement_status"],
                json!("measured"),
                "expected measured on {uri}: {parsed}"
            );
            assert_eq!(
                parsed["measurement_state"],
                json!("measured"),
                "expected measurement_state=measured on {uri}"
            );
            assert_eq!(
                parsed["source"],
                json!("postgres-direct"),
                "expected postgres-direct on {uri}"
            );
            assert_eq!(parsed["grants_execution_authority"], json!(false));
            if uri == "/api/v4/agents/summary" {
                assert_eq!(parsed["data"]["window_days"], json!(7));
                let loki = &parsed["data"]["pantheon_activity"]["Loki"];
                assert_eq!(loki["observed"], json!(true));
                if loki["event_count"].as_i64().unwrap_or(0) == 0 {
                    assert_eq!(loki["status"], json!("idle"));
                    assert_eq!(loki["activity_label"], json!("최근 7일 활동 0건 · 대기"));
                }
            }
            if uri == "/api/v4/agents/pantheon/loki" {
                assert_eq!(parsed["agent"]["accept_autonomous_upstream"], json!(true));
                assert_eq!(parsed["live_activity"]["window_days"], json!(7));
            }
        }
        Ok(())
    }
}
