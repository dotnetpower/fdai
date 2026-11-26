//! Domain 8 (`chat`, 3-pane workspace + SSE) PostgreSQL repository.
//! Provides bounded, read-only SQL grounding against local PostgreSQL tables
//! (`conversation_outbound_delivery`, `ontology_resource`, `ontology_link`,
//! `audit_log`, `operator_incident_projection`, `llm_invocation`).

use crate::db::{cell_i64, cell_str, quote_like_contains, DbHandle};
use fdai_adapter_postgres::pg_quote_literal;
use serde_json::{json, Value};
use std::time::Instant;

#[derive(Debug, Clone)]
pub struct ChatResourceRow {
    pub id: String,
    pub object_type: String,
    pub name: String,
    pub location: String,
    pub revision: i64,
    pub updated_at: String,
}

#[derive(Debug, Clone)]
pub struct ChatLinkRow {
    pub link_type: String,
    pub from_id: String,
    pub to_id: String,
}

#[derive(Debug, Clone)]
pub struct ChatIncidentRow {
    pub correlation_id: String,
    pub state: String,
    pub vertical: String,
    pub severity: String,
    pub incident_number: String,
}

#[derive(Debug, Clone)]
pub struct ChatAuditRow {
    pub seq: i64,
    pub actor: String,
    pub action_kind: String,
    pub mode: String,
    pub correlation_id: String,
    pub entry_hash: String,
    pub created_at: String,
}

#[derive(Debug, Clone)]
pub struct ChatDbEvidence {
    pub keywords: Vec<String>,
    pub keyword_matched: bool,
    pub step_labels: [String; 3],
    pub step_durations_ms: [u64; 3],
    pub resources_total: i64,
    pub azure_resources_total: i64,
    pub connected_nodes: i64,
    pub broken_links: i64,
    pub links_total: i64,
    pub distinct_link_types: i64,
    pub distinct_object_types: i64,
    pub rules_total: i64,
    pub policies_total: i64,
    pub audits_total: i64,
    pub incidents_total: i64,
    pub deliveries_total: i64,
    pub llm_invocations_total: i64,
    pub focus_cost_export_count: i64,
    pub matched_resources: Vec<ChatResourceRow>,
    pub matched_links: Vec<ChatLinkRow>,
    pub matched_rules: Vec<String>,
    pub incidents: Vec<ChatIncidentRow>,
    pub recent_audits: Vec<ChatAuditRow>,
    pub latest_audit_seq: Option<i64>,
    pub latest_audit_hash_prefix: String,
    pub latest_audit_at: String,
}

const ENTITY_DISPLAY_NAME_SQL: &str = "COALESCE(\
    NULLIF(trim(properties->>'name'), ''), \
    NULLIF(trim(properties->>'title'), ''), \
    NULLIF(trim(properties->>'display_name'), ''), \
    NULLIF(trim(properties->>'mechanism_id'), ''), \
    NULLIF(trim(properties->>'semantic_id'), ''), \
    NULLIF(trim(properties->>'provider_type'), ''), \
    id)";

fn short_resource_label(id_or_name: &str) -> String {
    let trimmed = id_or_name.trim();
    if trimmed.is_empty() {
        return String::from("unnamed-entity");
    }
    if let Some(last) = trimmed.rsplit('/').next() {
        if !last.is_empty() {
            return last.to_string();
        }
    }
    trimmed.to_string()
}

/// Produce a clean, human-readable display name even for ontology entities whose
/// `properties->>'name'` is NULL (e.g., `FrameworkControl`, `PolicyArtifact`,
/// `BenchmarkValidation`, `DiagnosticMechanism`, `ActionType`, `Rule`, `ResourceClass`).
#[must_use]
pub fn display_name_for_entity(id: &str, object_type: &str, raw_name: &str) -> String {
    let name_trim = raw_name.trim();
    let id_trim = id.trim();

    if !name_trim.is_empty() && name_trim != id_trim {
        if name_trim.starts_with("scope-") && name_trim.contains('/') {
            return short_resource_label(name_trim);
        }
        return name_trim.to_string();
    }

    if id_trim.is_empty() {
        return if object_type.trim().is_empty() {
            String::from("온톨로지 엔티티")
        } else {
            object_type.trim().to_string()
        };
    }

    if let Some(rest) = id_trim.strip_prefix("policies/") {
        let stripped = rest.strip_suffix(".rego").unwrap_or(rest);
        return stripped.replace('/', " · ").replace('_', "-");
    }
    if let Some(rest) = id_trim.strip_prefix("framework-control:") {
        let core = rest.split('@').next().unwrap_or(rest);
        return core.replace(':', " · ");
    }
    if let Some(rest) = id_trim.strip_prefix("control-objective:") {
        let core = rest.split('@').next().unwrap_or(rest);
        return core.replace('.', " · ");
    }
    if let Some(rest) = id_trim.strip_prefix("diagnostic-mechanism:") {
        return rest.replace('_', "-");
    }
    if let Some(rest) = id_trim.strip_prefix("benchmark-validation:") {
        let short_hex: String = rest.chars().take(10).collect();
        return format!("벤치마크 검증 ({short_hex})");
    }
    if let Some(rest) = id_trim.strip_prefix("class.") {
        return rest.to_string();
    }
    if let Some(rest) = id_trim.strip_prefix("property.") {
        return rest.replace('.', " · ");
    }
    if (id_trim.starts_with("review-") || id_trim.starts_with("check-")) && id_trim.len() > 18 {
        let short_id: String = id_trim.chars().take(15).collect();
        return format!("{short_id}...");
    }
    if id_trim.contains('/') {
        return short_resource_label(id_trim);
    }
    if matches!(object_type, "ActionType" | "Rule") && id_trim.contains('.') {
        return id_trim.replace('.', " · ");
    }
    id_trim.to_string()
}

fn connectivity_pct(connected: i64, total: i64) -> Option<f64> {
    if total <= 0 {
        return None;
    }
    let pct = (connected as f64) * 100.0 / (total as f64);
    Some((pct * 10.0).round() / 10.0)
}

fn hash_prefix(hash: &str) -> String {
    let clean: String = hash
        .trim()
        .chars()
        .filter(|c| c.is_ascii_hexdigit())
        .take(12)
        .collect();
    if clean.is_empty() {
        String::from("unhashed")
    } else {
        clean
    }
}

fn icon_for_resource(id_or_type: &str) -> &'static str {
    let lower = id_or_type.to_ascii_lowercase();
    if lower.contains("postgres") || lower.contains("pg-") || lower.contains("sql") {
        "/azure-icons/postgresql.svg"
    } else if lower.contains("vault") || lower.contains("kv-") || lower.contains("keyvault") {
        "/azure-icons/key-vault.svg"
    } else if lower.contains("storage") || lower.contains("cost") || lower.contains("disk") {
        "/azure-icons/storage-account.svg"
    } else if lower.contains("network") || lower.contains("loadbalancer") || lower.contains("nsg") {
        "/azure-icons/monitor.svg"
    } else {
        "/azure-icons/kubernetes-services.svg"
    }
}

fn extract_query_keywords(prompt: &str, selected_node: &str) -> Vec<String> {
    const STOPWORDS: [&str; 24] = [
        "the", "and", "for", "with", "from", "that", "this", "what", "how", "why", "show",
        "check", "status", "summary", "please", "help", "risks", "approvals", "ontology",
        "trace", "active", "command", "deck", "chat",
    ];
    let mut out: Vec<String> = Vec::new();
    let mut push_unique = |tok: String| {
        let low = tok.trim().to_ascii_lowercase();
        if low.len() < 2 || STOPWORDS.contains(&low.as_str()) {
            return;
        }
        if !out.iter().any(|existing| existing == &low) && out.len() < 6 {
            out.push(low);
        }
    };

    for raw_part in prompt.split(|c: char| !c.is_ascii_alphanumeric() && c != '-' && c != '_') {
        let cleaned = raw_part.trim_matches(|c: char| c == '-' || c == '_');
        if cleaned.len() >= 3 {
            push_unique(cleaned.to_string());
        }
    }

    let selected_clean = selected_node.trim();
    if !selected_clean.is_empty() && selected_clean.len() >= 3 {
        push_unique(selected_clean.to_string());
    }

    let ko_mappings: [(&str, &str); 14] = [
        ("쿠버네티스", "aks"),
        ("노드", "aks"),
        ("클러스터", "aks"),
        ("포스트그레스", "postgresql"),
        ("데이터베이스", "postgresql"),
        ("키볼트", "vault"),
        ("예외", "vault"),
        ("보안", "security"),
        ("규칙", "rule"),
        ("정책", "policy"),
        ("비용", "cost"),
        ("미수집", "cost"),
        ("워커", "worker"),
        ("디스크", "disk"),
    ];
    for (ko_term, ascii_kw) in ko_mappings {
        if prompt.contains(ko_term) {
            push_unique(ascii_kw.to_string());
        }
    }

    // If hyphenated identifiers (e.g. `prod-aks-02`, `pg-orders-db`, `kv-prod-kr`) did not include
    // their resource family token separately, also add recognizable Azure family hints.
    let combined_lower = format!("{} {}", prompt, selected_node).to_ascii_lowercase();
    for (needle, family) in [
        ("aks", "aks"),
        ("pg-", "postgresql"),
        ("postgres", "postgresql"),
        ("kv-", "vault"),
        ("vault", "vault"),
        ("inc-", "inc"),
        ("gpu", "gpu"),
    ] {
        if combined_lower.contains(needle) {
            push_unique(family.to_string());
        }
    }

    out
}

pub async fn fetch_chat_health(db: &DbHandle) -> Value {
    let (res_q, link_q, audit_q, inc_q, deliv_q, llm_q) = tokio::join!(
        db.query_single_readonly(
            "SELECT count(*), \
             max(to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')) \
             FROM ontology_resource"
        ),
        db.query_single_readonly("SELECT count(*) FROM ontology_link"),
        db.query_single_readonly(
            "SELECT count(*), max(seq), \
             max(to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')) \
             FROM audit_log"
        ),
        db.query_single_readonly("SELECT count(*) FROM operator_incident_projection"),
        db.query_single_readonly("SELECT count(*) FROM conversation_outbound_delivery"),
        db.query_single_readonly("SELECT count(*) FROM llm_invocation"),
    );

    match (res_q, link_q, audit_q, inc_q, deliv_q, llm_q) {
        (Ok(r), Ok(l), Ok(a), Ok(i), Ok(d), Ok(m)) => {
            let rr = r.rows.first().map(Vec::as_slice).unwrap_or(&[]);
            let lr = l.rows.first().map(Vec::as_slice).unwrap_or(&[]);
            let ar = a.rows.first().map(Vec::as_slice).unwrap_or(&[]);
            let ir = i.rows.first().map(Vec::as_slice).unwrap_or(&[]);
            let dr = d.rows.first().map(Vec::as_slice).unwrap_or(&[]);
            let mr = m.rows.first().map(Vec::as_slice).unwrap_or(&[]);

            json!({
                "measurement_status": "measured",
                "measurement_state": "measured",
                "source": "postgres-direct",
                "domain": "chat",
                "available": true,
                "mode": "postgres-direct-readonly",
                "read_only_boundary": true,
                "unmeasured_never_zero": true,
                "sse_endpoint": "/api/v4/chat/stream",
                "counts": {
                    "ontology_resources": cell_i64(rr, 0),
                    "ontology_links": cell_i64(lr, 0),
                    "audit_log": cell_i64(ar, 0),
                    "incident_projections": cell_i64(ir, 0),
                    "outbound_deliveries": cell_i64(dr, 0),
                    "llm_invocations": cell_i64(mr, 0)
                },
                "latest_audit_seq": cell_i64(ar, 1),
                "latest_audit_at": cell_str(ar, 2),
                "latest_resource_at": cell_str(rr, 1)
            })
        }
        _ => db.not_measured("chat", "/api/v4/chat/health", "postgres_unreachable"),
    }
}

pub async fn fetch_chat_sessions(db: &DbHandle) -> Value {
    fetch_chat_sessions_filtered(db, "all", "").await
}

pub async fn fetch_chat_sessions_filtered(
    db: &DbHandle,
    filter: &str,
    search: &str,
) -> Value {
    let deliv_sql = "SELECT delivery_id, COALESCE(conversation_id, ''), channel_kind, state, \
                     COALESCE(response->>'summary', ''), COALESCE(scope_ref, ''), \
                     to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                     FROM conversation_outbound_delivery ORDER BY created_at DESC LIMIT 50";
    let inc_sql = "SELECT correlation_id, projected_state, projected_vertical, projected_severity, \
                   COALESCE(canonical_incident_number, correlation_id), \
                   COALESCE(search_document, '') \
                   FROM operator_incident_projection ORDER BY last_seq DESC LIMIT 20";

    let (deliv_res, inc_res) = tokio::join!(
        db.query_single_readonly(deliv_sql),
        db.query_single_readonly(inc_sql),
    );
    let Ok(d_res) = deliv_res else {
        return db.not_measured("chat", "/api/v4/chat/sessions", "postgres_unreachable");
    };
    let inc_rows = inc_res.map(|r| r.rows).unwrap_or_default();

    let total_deliveries = d_res.rows.len();
    let total_incidents = inc_rows.len();

    let mut all_sessions: Vec<Value> = Vec::with_capacity(total_deliveries + total_incidents);

    for r in &inc_rows {
        let corr = cell_str(r, 0);
        let p_state = cell_str(r, 1);
        let vertical = cell_str(r, 2);
        let severity = cell_str(r, 3);
        let inc_no = cell_str(r, 4);
        let doc = cell_str(r, 5);
        let unread = p_state.eq_ignore_ascii_case("in_progress");
        let starred = severity.eq_ignore_ascii_case("high") || severity.eq_ignore_ascii_case("critical");
        let title = format!("{inc_no} · {vertical} ({severity})");
        let subtitle = format!("인시던트 프로젝션 · {p_state} · {corr}");
        let context = format!("인시던트 · {inc_no}");
        let prompt = format!(
            "{inc_no}({corr}) 인시던트의 현재 상태({p_state})와 관련 온톨로지·감사 이력 근거를 요약해 줘."
        );
        all_sessions.push(json!({
            "id": corr,
            "record_kind": "incident_projection",
            "category": "incidents",
            "title": title,
            "subtitle": subtitle,
            "context": context,
            "summary": doc,
            "prompt": prompt,
            "state": p_state,
            "severity": severity,
            "vertical": vertical,
            "incident_number": inc_no,
            "unread": unread,
            "starred": starred,
            "measurement_status": "measured",
            "measurement_state": "measured",
            "source": "postgres-direct"
        }));
    }

    for (idx, r) in d_res.rows.iter().enumerate() {
        let delivery_id = cell_str(r, 0);
        let conversation_id = cell_str(r, 1);
        let channel_kind = cell_str(r, 2);
        let state = cell_str(r, 3);
        let summary = cell_str(r, 4);
        let scope_ref = cell_str(r, 5);
        let created_at = cell_str(r, 6);
        let conv_label = if conversation_id.is_empty() {
            delivery_id.clone()
        } else {
            conversation_id.clone()
        };
        let title = if summary.is_empty() {
            format!("{conv_label} ({channel_kind})")
        } else {
            format!("{conv_label} · {summary}")
        };
        let subtitle = format!("{channel_kind} · {state} · {created_at}");
        let context = if scope_ref.is_empty() {
            format!("대화 전달 · {conv_label}")
        } else {
            format!("대화 · {scope_ref}")
        };
        let prompt = format!(
            "대화 세션 {conv_label}({delivery_id})의 전달 상태({state})와 최신 온톨로지·감사 근거를 점검해 줘."
        );
        all_sessions.push(json!({
            "id": delivery_id,
            "delivery_id": delivery_id,
            "conversation_id": conversation_id,
            "channel_kind": channel_kind,
            "state": state,
            "created_at": created_at,
            "record_kind": "outbound_delivery",
            "category": "governance",
            "title": title,
            "subtitle": subtitle,
            "context": context,
            "summary": summary,
            "prompt": prompt,
            "unread": !state.eq_ignore_ascii_case("delivered"),
            "starred": idx == 0,
            "measurement_status": "measured",
            "measurement_state": "measured",
            "source": "postgres-direct"
        }));
    }

    let q_low = search.trim().to_ascii_lowercase();
    let filtered: Vec<Value> = all_sessions
        .into_iter()
        .filter(|s| {
            let unread = s.get("unread").and_then(Value::as_bool).unwrap_or(false);
            let starred = s.get("starred").and_then(Value::as_bool).unwrap_or(false);
            let category = s.get("category").and_then(Value::as_str).unwrap_or("");
            if filter == "incidents" && category != "incidents" {
                return false;
            }
            if filter == "governance" && category != "governance" {
                return false;
            }
            if filter == "unread" && !unread {
                return false;
            }
            if filter == "starred" && !starred {
                return false;
            }
            if !q_low.is_empty() {
                let hay = format!(
                    "{} {} {} {} {}",
                    s.get("id").and_then(Value::as_str).unwrap_or(""),
                    s.get("title").and_then(Value::as_str).unwrap_or(""),
                    s.get("subtitle").and_then(Value::as_str).unwrap_or(""),
                    s.get("context").and_then(Value::as_str).unwrap_or(""),
                    s.get("summary").and_then(Value::as_str).unwrap_or(""),
                )
                .to_ascii_lowercase();
                return hay.contains(&q_low);
            }
            true
        })
        .collect();

    json!({
        "measurement_status": "measured",
        "measurement_state": "measured",
        "source": "postgres-direct",
        "domain": "chat",
        "read_only_boundary": true,
        "unmeasured_never_zero": true,
        "filter": filter,
        "query": q_low,
        "count": filtered.len(),
        "total_deliveries": total_deliveries,
        "total_incidents": total_incidents,
        "sessions": filtered
    })
}

pub async fn fetch_chat_context(db: &DbHandle) -> Value {
    fetch_chat_context_for_node(db, None).await
}

pub async fn fetch_chat_context_for_node(db: &DbHandle, selected_node: Option<&str>) -> Value {
    let counts_sql = "SELECT count(*), \
                      count(*) FILTER (WHERE object_type = 'Resource'), \
                      count(*) FILTER (WHERE object_type = 'Rule'), \
                      count(*) FILTER (WHERE object_type = 'PolicyArtifact'), \
                      count(*) FILTER (WHERE object_type = 'ActionType'), \
                      count(*) FILTER (WHERE id ILIKE '%focus-cost-export%'), \
                      count(DISTINCT object_type), \
                      count(*) FILTER (WHERE EXISTS (SELECT 1 FROM ontology_link l WHERE l.from_id = ontology_resource.id OR l.to_id = ontology_resource.id)) \
                      FROM ontology_resource";
    let link_cnt_sql = "SELECT count(*), count(DISTINCT link_type), \
                        count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM ontology_resource r WHERE r.id = ontology_link.from_id) \
                                            OR NOT EXISTS (SELECT 1 FROM ontology_resource r WHERE r.id = ontology_link.to_id)) \
                        FROM ontology_link";
    let audit_sql = "SELECT count(*), max(seq), \
                     max(to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')) \
                     FROM audit_log";
    let latest_audit_sql = "SELECT seq, actor, action_kind, mode, COALESCE(correlation_id, ''), \
                            entry_hash, \
                            to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                            FROM audit_log ORDER BY seq DESC LIMIT 5";
    let inc_sql = "SELECT correlation_id, projected_state, projected_vertical, projected_severity, \
                   COALESCE(canonical_incident_number, correlation_id) \
                   FROM operator_incident_projection ORDER BY last_seq DESC LIMIT 10";
    let meta_sql = "SELECT (SELECT count(*) FROM conversation_outbound_delivery), \
                    (SELECT count(*) FROM llm_invocation)";
    let subs_sql = "SELECT COALESCE(NULLIF(properties->>'subscription_id',''), NULLIF(properties->'properties'->>'subscriptionId',''), split_part(id, '/', 3)) AS sub_key, \
                    count(*) \
                    FROM ontology_resource WHERE object_type = 'Resource' \
                    GROUP BY 1 ORDER BY 2 DESC LIMIT 10";
    let rules_sample_sql = format!(
        "SELECT id, object_type, {ENTITY_DISPLAY_NAME_SQL} \
         FROM ontology_resource WHERE object_type = 'Rule' \
         ORDER BY updated_at DESC LIMIT 5"
    );

    let node_filter = selected_node
        .map(str::trim)
        .filter(|s| !s.is_empty());
    let resources_sql = if let Some(node) = node_filter {
        let pat = quote_like_contains(node);
        format!(
            "SELECT id, object_type, {ENTITY_DISPLAY_NAME_SQL}, \
             COALESCE(properties->>'location', ''), revision, \
             to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
             FROM ontology_resource \
             WHERE object_type = 'Resource' \
             ORDER BY (CASE WHEN id ILIKE {pat} ESCAPE '\\' OR COALESCE(properties->>'name', '') ILIKE {pat} ESCAPE '\\' THEN 0 ELSE 1 END), \
                      updated_at DESC \
             LIMIT 20"
        )
    } else {
        format!(
            "SELECT id, object_type, {ENTITY_DISPLAY_NAME_SQL}, \
             COALESCE(properties->>'location', ''), revision, \
             to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
             FROM ontology_resource WHERE object_type = 'Resource' ORDER BY updated_at DESC LIMIT 20"
        )
    };

    let (cnt_q, link_q, audit_q, latest_a_q, inc_q, meta_q, res_q, subs_q, rules_q) = tokio::join!(
        db.query_single_readonly(counts_sql),
        db.query_single_readonly(link_cnt_sql),
        db.query_single_readonly(audit_sql),
        db.query_single_readonly(latest_audit_sql),
        db.query_single_readonly(inc_sql),
        db.query_single_readonly(meta_sql),
        db.query_single_readonly(&resources_sql),
        db.query_single_readonly(subs_sql),
        db.query_single_readonly(&rules_sample_sql),
    );

    let (Ok(cnt_r), Ok(link_r), Ok(audit_r), Ok(res_r)) = (cnt_q, link_q, audit_q, res_q) else {
        return db.not_measured("chat", "/api/v4/chat/context", "postgres_unreachable");
    };

    let cr = cnt_r.rows.first().map(Vec::as_slice).unwrap_or(&[]);
    let lr = link_r.rows.first().map(Vec::as_slice).unwrap_or(&[]);
    let ar = audit_r.rows.first().map(Vec::as_slice).unwrap_or(&[]);
    let mr = meta_q
        .ok()
        .and_then(|v| v.rows.into_iter().next())
        .unwrap_or_default();

    let res_total = cell_i64(cr, 0).unwrap_or(0);
    let resource_instances = cell_i64(cr, 1).unwrap_or(0);
    let rules_total = cell_i64(cr, 2).unwrap_or(0);
    let policies_total = cell_i64(cr, 3).unwrap_or(0);
    let actions_total = cell_i64(cr, 4).unwrap_or(0);
    let focus_cost_count = cell_i64(cr, 5).unwrap_or(0);
    let distinct_object_types = cell_i64(cr, 6).unwrap_or(0);
    let connected_nodes = cell_i64(cr, 7).unwrap_or(0);
    let conn_pct = connectivity_pct(connected_nodes, res_total);
    let links_total = cell_i64(lr, 0).unwrap_or(0);
    let distinct_link_types = cell_i64(lr, 1).unwrap_or(0);
    let broken_links = cell_i64(lr, 2).unwrap_or(0);
    let audits_total = cell_i64(ar, 0).unwrap_or(0);
    let latest_audit_seq = cell_i64(ar, 1);
    let latest_audit_at = cell_str(ar, 2);
    let deliveries_total = cell_i64(&mr, 0).unwrap_or(0);
    let llm_total = cell_i64(&mr, 1).unwrap_or(0);

    let grounded_resources: Vec<Value> = res_r
        .rows
        .iter()
        .map(|r| {
            let id = cell_str(r, 0);
            let obj_type = cell_str(r, 1);
            let raw_name = cell_str(r, 2);
            let display_name = display_name_for_entity(&id, &obj_type, &raw_name);
            json!({
                "id": id,
                "object_type": obj_type,
                "name": display_name,
                "short_name": display_name,
                "location": cell_str(r, 3),
                "revision": cell_i64(r, 4),
                "updated_at": cell_str(r, 5),
                "icon": icon_for_resource(&id)
            })
        })
        .collect();

    // Fetch 1-hop ontology links for the leading grounded resource so the right context panel
    // displays genuine topology relationships.
    let mut sample_links: Vec<Value> = Vec::new();
    if let Some(first_id) = res_r.rows.first().map(|r| cell_str(r, 0)) {
        let q_id = pg_quote_literal(&first_id);
        let lsql = format!(
            "SELECT link_type, from_id, to_id FROM ontology_link \
             WHERE from_id = {q_id} OR to_id = {q_id} ORDER BY created_at DESC LIMIT 8"
        );
        if let Ok(lr_rows) = db.query_single_readonly(&lsql).await {
            for row in &lr_rows.rows {
                let from_id = cell_str(row, 1);
                let to_id = cell_str(row, 2);
                sample_links.push(json!({
                    "link_type": cell_str(row, 0),
                    "from_id": from_id,
                    "from_label": display_name_for_entity(&from_id, "", &from_id),
                    "to_id": to_id,
                    "to_label": display_name_for_entity(&to_id, "", &to_id)
                }));
            }
        }
    }

    let incidents: Vec<Value> = inc_q
        .ok()
        .map(|res| {
            res.rows
                .iter()
                .map(|r| {
                    json!({
                        "correlation_id": cell_str(r, 0),
                        "projected_state": cell_str(r, 1),
                        "projected_vertical": cell_str(r, 2),
                        "projected_severity": cell_str(r, 3),
                        "incident_number": cell_str(r, 4)
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    let active_incidents = incidents
        .iter()
        .filter(|i| {
            i.get("projected_state")
                .and_then(Value::as_str)
                .is_some_and(|s| s.eq_ignore_ascii_case("in_progress"))
        })
        .count();

    let recent_audits: Vec<Value> = latest_a_q
        .ok()
        .map(|res| {
            res.rows
                .iter()
                .map(|r| {
                    let full_hash = cell_str(r, 5);
                    json!({
                        "seq": cell_i64(r, 0),
                        "actor": cell_str(r, 1),
                        "action_kind": cell_str(r, 2),
                        "mode": cell_str(r, 3),
                        "correlation_id": cell_str(r, 4),
                        "hash_prefix": hash_prefix(&full_hash),
                        "created_at": cell_str(r, 6)
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    let latest_hash = recent_audits
        .first()
        .and_then(|v| v.get("hash_prefix"))
        .and_then(Value::as_str)
        .unwrap_or("unhashed");

    let conn_label = conn_pct
        .map(|p| format!("{p:.1}%"))
        .unwrap_or_else(|| "미측정".to_string());
    let sources = vec![
        json!({
            "id": "ontology-inventory",
            "label": "온톨로지 · 리소스 인벤토리",
            "agent": "Muninn",
            "icon": "/agent-icons/muninn.svg",
            "state": "connected",
            "detail": format!(
                "PostgreSQL 실측 · 엔티티 {res_total}건 (Azure 리소스 {resource_instances}건) · 링크 {links_total}건 · 연결률 {conn_label} · 깨진 링크 {broken_links}건"
            )
        }),
        json!({
            "id": "audit-log",
            "label": "감사 로그 (최근 7일 · SHA-256)",
            "agent": "Saga",
            "icon": "/agent-icons/saga.svg",
            "state": "connected",
            "detail": format!(
                "PostgreSQL 실측 · 최근 7일 감사 {audits_total}건 · 최신 #{} (sha256:{latest_hash})",
                latest_audit_seq.unwrap_or(0)
            )
        }),
        json!({
            "id": "hil-queue",
            "label": "인시던트 · 승인 연계 프로젝션",
            "agent": "Var",
            "icon": "/agent-icons/var.svg",
            "state": "connected",
            "detail": format!(
                "PostgreSQL 실측 · 인시던트 {}건 (진행 중 {active_incidents}건) · 액션타입 {actions_total}건",
                incidents.len()
            )
        }),
        json!({
            "id": "operating-rules",
            "label": "운영 규칙 (MCSB / WARA)",
            "agent": "Forseti",
            "icon": "/agent-icons/forseti.svg",
            "state": "connected",
            "detail": format!("PostgreSQL 실측 · 활성 규칙 {rules_total}개 · 정책 아티팩트 {policies_total}개")
        }),
        json!({
            "id": "knowledge-docs",
            "label": "대화 전달 · LLM 호출 (최근 7일)",
            "agent": "Odin",
            "icon": "/agent-icons/odin.svg",
            "state": "connected",
            "detail": format!("PostgreSQL 실측 · 대화 전달 {deliveries_total}건 · LLM 호출 {llm_total}건")
        }),
        json!({
            "id": "focus-cost-export",
            "label": "focus-cost-export (비용 내보내기)",
            "agent": "Njord",
            "icon": "/azure-icons/storage-account.svg",
            "state": if focus_cost_count > 0 { "connected" } else { "unavailable" },
            "detail": if focus_cost_count > 0 {
                format!("PostgreSQL 실측 · focus-cost-export 리소스 {focus_cost_count}건")
            } else {
                "데이터 없음 (미수집 · 0 대체 금지)".to_string()
            }
        }),
    ];

    let subscriptions: Vec<Value> = subs_q
        .ok()
        .map(|res| {
            res.rows
                .iter()
                .filter_map(|row| {
                    let raw = cell_str(row, 0);
                    let trimmed = raw.trim();
                    if trimmed.is_empty() {
                        return None;
                    }
                    let cnt = cell_i64(row, 1).unwrap_or(0);
                    let prefix: String = trimmed.chars().take(8).collect();
                    let masked = if trimmed.len() > 10 {
                        format!("sub-{prefix}...")
                    } else {
                        trimmed.to_string()
                    };
                    Some(json!({
                        "id": trimmed,
                        "masked": masked,
                        "label": format!("{masked} ({cnt}개 리소스)"),
                        "resource_count": cnt
                    }))
                })
                .collect()
        })
        .unwrap_or_default();

    let top_rules: Vec<String> = rules_q
        .ok()
        .map(|res| {
            res.rows
                .iter()
                .map(|r| {
                    let rid = cell_str(r, 0);
                    let otype = cell_str(r, 1);
                    let rname = cell_str(r, 2);
                    display_name_for_entity(&rid, &otype, &rname)
                })
                .filter(|s| !s.is_empty())
                .collect()
        })
        .unwrap_or_default();

    json!({
        "measurement_status": "measured",
        "measurement_state": "measured",
        "source": "postgres-direct",
        "domain": "chat",
        "counts": {
            "ontology_resources": res_total,
            "resource_instances": resource_instances,
            "connected_nodes": connected_nodes,
            "connectivity_pct": conn_pct,
            "broken_links": broken_links,
            "distinct_object_types": distinct_object_types,
            "distinct_link_types": distinct_link_types,
            "ontology_links": links_total,
            "rules": rules_total,
            "policy_artifacts": policies_total,
            "action_types": actions_total,
            "audit_log": audits_total,
            "incident_projections": incidents.len(),
            "active_incidents": active_incidents,
            "outbound_deliveries": deliveries_total,
            "llm_invocations": llm_total,
            "focus_cost_export": focus_cost_count
        },
        "latest_audit_seq": latest_audit_seq,
        "latest_audit_hash_prefix": latest_hash,
        "latest_audit_at": latest_audit_at,
        "subscriptions": subscriptions,
        "top_rules": top_rules,
        "sources": sources,
        "grounded_resources": grounded_resources,
        "links": sample_links,
        "incidents": incidents,
        "recent_audits": recent_audits
    })
}

pub async fn query_chat_evidence(
    db: &DbHandle,
    prompt: &str,
    selected_node: &str,
) -> Option<ChatDbEvidence> {
    let keywords = extract_query_keywords(prompt, selected_node);

    // Stage 1: Snapshot & resource/incident lookup
    let t1 = Instant::now();
    let res_where = if keywords.is_empty() {
        String::from("WHERE object_type = 'Resource'")
    } else {
        let conds: Vec<String> = keywords
            .iter()
            .take(4)
            .map(|kw| {
                let pat = quote_like_contains(kw);
                format!(
                    "(id ILIKE {pat} ESCAPE '\\' OR COALESCE(properties->>'name', '') ILIKE {pat} ESCAPE '\\' \
                     OR COALESCE(properties->>'title', '') ILIKE {pat} ESCAPE '\\' \
                     OR COALESCE(properties->>'mechanism_id', '') ILIKE {pat} ESCAPE '\\' \
                     OR object_type ILIKE {pat} ESCAPE '\\')"
                )
            })
            .collect();
        format!("WHERE {}", conds.join(" OR "))
    };
    let primary_rank_sql = if let Some(first_kw) = keywords.first() {
        let pat = quote_like_contains(first_kw);
        format!(
            "(CASE WHEN id ILIKE {pat} ESCAPE '\\' OR COALESCE(properties->>'name', '') ILIKE {pat} ESCAPE '\\' \
                   OR COALESCE(properties->>'title', '') ILIKE {pat} ESCAPE '\\' THEN 0 \
                   WHEN object_type = 'Resource' THEN 1 ELSE 2 END)"
        )
    } else {
        String::from("(CASE WHEN object_type = 'Resource' THEN 0 ELSE 1 END)")
    };
    let match_res_sql = format!(
        "SELECT id, object_type, {ENTITY_DISPLAY_NAME_SQL}, \
         COALESCE(properties->>'location', ''), revision, \
         to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
         FROM ontology_resource {res_where} \
         ORDER BY {primary_rank_sql}, updated_at DESC \
         LIMIT 6"
    );
    let counts_sql = "SELECT count(*), \
                      count(*) FILTER (WHERE object_type = 'Resource'), \
                      count(*) FILTER (WHERE object_type = 'Rule'), \
                      count(*) FILTER (WHERE object_type = 'PolicyArtifact'), \
                      count(*) FILTER (WHERE id ILIKE '%focus-cost-export%'), \
                      count(DISTINCT object_type), \
                      count(*) FILTER (WHERE EXISTS (SELECT 1 FROM ontology_link l WHERE l.from_id = ontology_resource.id OR l.to_id = ontology_resource.id)) \
                      FROM ontology_resource";
    let inc_sql = "SELECT correlation_id, projected_state, projected_vertical, projected_severity, \
                   COALESCE(canonical_incident_number, correlation_id) \
                   FROM operator_incident_projection ORDER BY last_seq DESC LIMIT 5";

    let (match_q, counts_q, inc_q) = tokio::join!(
        db.query_single_readonly(&match_res_sql),
        db.query_single_readonly(counts_sql),
        db.query_single_readonly(inc_sql),
    );
    let Ok(counts_res) = counts_q else {
        return None;
    };
    let cr = counts_res.rows.first().map(Vec::as_slice).unwrap_or(&[]);
    let resources_total = cell_i64(cr, 0).unwrap_or(0);
    let azure_resources_total = cell_i64(cr, 1).unwrap_or(0);
    let rules_total = cell_i64(cr, 2).unwrap_or(0);
    let policies_total = cell_i64(cr, 3).unwrap_or(0);
    let focus_cost_export_count = cell_i64(cr, 4).unwrap_or(0);
    let distinct_object_types = cell_i64(cr, 5).unwrap_or(0);
    let connected_nodes = cell_i64(cr, 6).unwrap_or(0);

    let mut matched_resources: Vec<ChatResourceRow> = match_q
        .ok()
        .map(|r| {
            r.rows
                .iter()
                .map(|row| {
                    let id = cell_str(row, 0);
                    let obj_type = cell_str(row, 1);
                    let raw_name = cell_str(row, 2);
                    let display_name = display_name_for_entity(&id, &obj_type, &raw_name);
                    ChatResourceRow {
                        id,
                        object_type: obj_type,
                        name: display_name,
                        location: cell_str(row, 3),
                        revision: cell_i64(row, 4).unwrap_or(0),
                        updated_at: cell_str(row, 5),
                    }
                })
                .collect()
        })
        .unwrap_or_default();

    let keyword_matched = !keywords.is_empty() && !matched_resources.is_empty();
    if matched_resources.is_empty() {
        let fallback_sql = format!(
            "SELECT id, object_type, {ENTITY_DISPLAY_NAME_SQL}, \
             COALESCE(properties->>'location', ''), revision, \
             to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
             FROM ontology_resource WHERE object_type = 'Resource' \
             ORDER BY updated_at DESC LIMIT 5"
        );
        if let Ok(fb) = db.query_single_readonly(&fallback_sql).await {
            matched_resources = fb
                .rows
                .iter()
                .map(|row| {
                    let id = cell_str(row, 0);
                    let obj_type = cell_str(row, 1);
                    let raw_name = cell_str(row, 2);
                    let display_name = display_name_for_entity(&id, &obj_type, &raw_name);
                    ChatResourceRow {
                        id,
                        object_type: obj_type,
                        name: display_name,
                        location: cell_str(row, 3),
                        revision: cell_i64(row, 4).unwrap_or(0),
                        updated_at: cell_str(row, 5),
                    }
                })
                .collect();
        }
    }

    let incidents: Vec<ChatIncidentRow> = inc_q
        .ok()
        .map(|r| {
            r.rows
                .iter()
                .map(|row| ChatIncidentRow {
                    correlation_id: cell_str(row, 0),
                    state: cell_str(row, 1),
                    vertical: cell_str(row, 2),
                    severity: cell_str(row, 3),
                    incident_number: cell_str(row, 4),
                })
                .collect()
        })
        .unwrap_or_default();
    let incidents_total = i64::try_from(incidents.len()).unwrap_or(0);
    let step1_ms = u64::try_from(t1.elapsed().as_millis()).unwrap_or(1).max(1);

    // Stage 2: Ontology links & active Rule/PolicyArtifact lookup
    let t2 = Instant::now();
    let links_sql = if !matched_resources.is_empty() {
        let quoted_ids: Vec<String> = matched_resources
            .iter()
            .take(5)
            .map(|r| pg_quote_literal(&r.id))
            .collect();
        let in_list = quoted_ids.join(", ");
        format!(
            "SELECT link_type, from_id, to_id FROM ontology_link \
             WHERE from_id IN ({in_list}) OR to_id IN ({in_list}) \
             ORDER BY created_at DESC LIMIT 8"
        )
    } else {
        "SELECT link_type, from_id, to_id FROM ontology_link ORDER BY created_at DESC LIMIT 6"
            .to_string()
    };
    let rules_sql = if let Some(first_kw) = keywords.first() {
        let pat = quote_like_contains(first_kw);
        format!(
            "SELECT id, object_type, {ENTITY_DISPLAY_NAME_SQL} FROM ontology_resource \
             WHERE object_type IN ('Rule', 'PolicyArtifact') \
             ORDER BY (CASE WHEN id ILIKE {pat} ESCAPE '\\' OR COALESCE(properties->>'title', '') ILIKE {pat} ESCAPE '\\' THEN 0 ELSE 1 END), updated_at DESC \
             LIMIT 5"
        )
    } else {
        format!(
            "SELECT id, object_type, {ENTITY_DISPLAY_NAME_SQL} FROM ontology_resource \
             WHERE object_type IN ('Rule', 'PolicyArtifact') \
             ORDER BY updated_at DESC LIMIT 5"
        )
    };

    let links_meta_sql = "SELECT count(*), count(DISTINCT link_type), \
                          count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM ontology_resource r WHERE r.id = ontology_link.from_id) \
                                              OR NOT EXISTS (SELECT 1 FROM ontology_resource r WHERE r.id = ontology_link.to_id)) \
                          FROM ontology_link";
    let (links_cnt_q, links_q, rules_q) = tokio::join!(
        db.query_single_readonly(links_meta_sql),
        db.query_single_readonly(&links_sql),
        db.query_single_readonly(&rules_sql),
    );
    let lmr = links_cnt_q
        .ok()
        .and_then(|r| r.rows.into_iter().next())
        .unwrap_or_default();
    let links_total = cell_i64(&lmr, 0).unwrap_or(0);
    let distinct_link_types = cell_i64(&lmr, 1).unwrap_or(0);
    let broken_links = cell_i64(&lmr, 2).unwrap_or(0);

    let mut matched_links: Vec<ChatLinkRow> = links_q
        .ok()
        .map(|r| {
            r.rows
                .iter()
                .map(|row| ChatLinkRow {
                    link_type: cell_str(row, 0),
                    from_id: cell_str(row, 1),
                    to_id: cell_str(row, 2),
                })
                .collect()
        })
        .unwrap_or_default();
    if matched_links.is_empty() {
        if let Ok(fb_links) = db
            .query_single_readonly(
                "SELECT link_type, from_id, to_id FROM ontology_link ORDER BY created_at DESC LIMIT 5",
            )
            .await
        {
            matched_links = fb_links
                .rows
                .iter()
                .map(|row| ChatLinkRow {
                    link_type: cell_str(row, 0),
                    from_id: cell_str(row, 1),
                    to_id: cell_str(row, 2),
                })
                .collect();
        }
    }

    let matched_rules: Vec<String> = rules_q
        .ok()
        .map(|r| {
            r.rows
                .iter()
                .map(|row| {
                    let rid = cell_str(row, 0);
                    let otype = cell_str(row, 1);
                    let rname = cell_str(row, 2);
                    display_name_for_entity(&rid, &otype, &rname)
                })
                .collect()
        })
        .unwrap_or_default();
    let step2_ms = u64::try_from(t2.elapsed().as_millis()).unwrap_or(1).max(1);

    // Stage 3: Audit log & conversation delivery verification
    let t3 = Instant::now();
    let audit_meta_sql = "SELECT count(*), max(seq), \
                          max(to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')) \
                          FROM audit_log";
    let recent_audit_sql = "SELECT seq, actor, action_kind, mode, COALESCE(correlation_id, ''), \
                            entry_hash, \
                            to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                            FROM audit_log ORDER BY seq DESC LIMIT 5";
    let counts_tail_sql = "SELECT (SELECT count(*) FROM conversation_outbound_delivery), \
                           (SELECT count(*) FROM llm_invocation)";

    let (audit_meta_q, recent_audit_q, counts_tail_q) = tokio::join!(
        db.query_single_readonly(audit_meta_sql),
        db.query_single_readonly(recent_audit_sql),
        db.query_single_readonly(counts_tail_sql),
    );

    let am = audit_meta_q
        .ok()
        .and_then(|r| r.rows.into_iter().next())
        .unwrap_or_default();
    let audits_total = cell_i64(&am, 0).unwrap_or(0);
    let latest_audit_seq = cell_i64(&am, 1);
    let latest_audit_at = cell_str(&am, 2);

    let recent_audits: Vec<ChatAuditRow> = recent_audit_q
        .ok()
        .map(|r| {
            r.rows
                .iter()
                .map(|row| ChatAuditRow {
                    seq: cell_i64(row, 0).unwrap_or(0),
                    actor: cell_str(row, 1),
                    action_kind: cell_str(row, 2),
                    mode: cell_str(row, 3),
                    correlation_id: cell_str(row, 4),
                    entry_hash: cell_str(row, 5),
                    created_at: cell_str(row, 6),
                })
                .collect()
        })
        .unwrap_or_default();

    let latest_audit_hash_prefix = recent_audits
        .first()
        .map(|a| hash_prefix(&a.entry_hash))
        .unwrap_or_else(|| String::from("unhashed"));

    let tail = counts_tail_q
        .ok()
        .and_then(|r| r.rows.into_iter().next())
        .unwrap_or_default();
    let deliveries_total = cell_i64(&tail, 0).unwrap_or(0);
    let llm_invocations_total = cell_i64(&tail, 1).unwrap_or(0);
    let step3_ms = u64::try_from(t3.elapsed().as_millis()).unwrap_or(1).max(1);

    let conn_label = connectivity_pct(connected_nodes, resources_total)
        .map(|p| format!("{p:.1}%"))
        .unwrap_or_else(|| "미측정".to_string());
    let step_labels = [
        format!(
            "PostgreSQL 실측 스냅샷 조회 - ontology_resource {}건(Azure {}건 · 연결률 {}) 중 {}건 · 인시던트 {}건",
            resources_total,
            azure_resources_total,
            conn_label,
            matched_resources.len(),
            incidents_total
        ),
        format!(
            "온톨로지 계통 · Forseti 정책 대조 - ontology_link {}건(깨진 링크 {}건 · 연관 {}건) · 규칙 {}개 · 정책 {}개",
            links_total,
            broken_links,
            matched_links.len(),
            rules_total,
            policies_total
        ),
        format!(
            "Saga 감사 이력 근거 요약 - 최근 7일 audit_log {}건 · 최신 #{} (sha256:{})",
            audits_total,
            latest_audit_seq.unwrap_or(0),
            latest_audit_hash_prefix
        ),
    ];

    Some(ChatDbEvidence {
        keywords,
        keyword_matched,
        step_labels,
        step_durations_ms: [step1_ms, step2_ms, step3_ms],
        resources_total,
        azure_resources_total,
        connected_nodes,
        broken_links,
        links_total,
        distinct_link_types,
        distinct_object_types,
        rules_total,
        policies_total,
        audits_total,
        incidents_total,
        deliveries_total,
        llm_invocations_total,
        focus_cost_export_count,
        matched_resources,
        matched_links,
        matched_rules,
        incidents,
        recent_audits,
        latest_audit_seq,
        latest_audit_hash_prefix,
        latest_audit_at,
    })
}

pub fn build_db_lineage_value(ev: &ChatDbEvidence, selected_node: &str) -> Value {
    let mut nodes: Vec<Value> = Vec::new();
    for (idx, r) in ev.matched_resources.iter().take(4).enumerate() {
        let short = display_name_for_entity(&r.id, &r.object_type, &r.name);
        let role = if idx == 0 {
            format!("대상 엔티티 · {} (Rev #{})", r.object_type, r.revision)
        } else {
            format!("연관 엔티티 · {} (Rev #{})", r.object_type, r.revision)
        };
        let detail = if r.location.is_empty() {
            format!("PostgreSQL 실측 · {}", r.id)
        } else {
            format!("PostgreSQL 실측 · {} · {}", r.location, r.id)
        };
        nodes.push(json!({
            "name": short,
            "id": r.id,
            "role": role,
            "icon": icon_for_resource(&r.id),
            "detail": detail
        }));
    }
    let edges: Vec<Value> = ev
        .matched_links
        .iter()
        .take(6)
        .map(|l| {
            json!({
                "link_type": l.link_type,
                "from": display_name_for_entity(&l.from_id, "", &l.from_id),
                "to": display_name_for_entity(&l.to_id, "", &l.to_id)
            })
        })
        .collect();

    json!({
        "selected": selected_node,
        "source": "postgres-direct",
        "nodes": nodes,
        "edges": edges
    })
}

pub fn short_id_label(raw: &str) -> String {
    display_name_for_entity(raw, "", raw)
}

pub fn short_hash_prefix(raw: &str) -> String {
    hash_prefix(raw)
}
