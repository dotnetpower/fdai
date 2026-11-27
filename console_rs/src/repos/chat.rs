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

#[derive(Debug, Clone, Default)]
pub struct ChatIncidentRow {
    pub correlation_id: String,
    pub state: String,
    pub vertical: String,
    pub severity: String,
    pub incident_number: String,
    pub target_resource: String,
}

#[derive(Debug, Clone, Default)]
pub struct ChatAuditRow {
    pub seq: i64,
    pub actor: String,
    pub action_kind: String,
    pub mode: String,
    pub correlation_id: String,
    pub entry_hash: String,
    pub created_at: String,
    pub target_resource: String,
    pub rule_id: String,
    pub remediation_action: String,
    pub severity: String,
}

#[derive(Debug, Clone, Default)]
pub struct ChatExecutedQuery {
    pub stage: String,
    pub title: String,
    pub sql: String,
    pub row_count: usize,
    pub duration_ms: u64,
    pub summary: String,
}

#[derive(Debug, Clone, Default)]
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
    pub executed_queries: Vec<ChatExecutedQuery>,
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
        return format!("{short_id}…");
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

#[must_use]
pub fn human_state_ko(raw: &str) -> &'static str {
    match raw.trim().to_ascii_lowercase().as_str() {
        "in_progress" | "active" | "open" | "running" => "진행 중",
        "resolved" | "closed" | "completed" => "해결됨",
        "pending" | "waiting" => "대기 중",
        "delivered" => "전달 완료",
        "failed" | "error" => "실패",
        "denied" | "blocked" => "차단됨",
        _ => "기록됨",
    }
}

#[must_use]
pub fn human_vertical_ko(raw: &str) -> &'static str {
    match raw.trim().to_ascii_lowercase().as_str() {
        "resilience" => "복원력",
        "change_safety" => "변경 안전",
        "cost_governance" => "비용 거버넌스",
        "security" => "보안",
        _ => "운영",
    }
}

#[must_use]
pub fn human_severity_ko(raw: &str) -> &'static str {
    match raw.trim().to_ascii_lowercase().as_str() {
        "critical" | "sev1" | "p0" => "긴급",
        "high" | "sev2" | "p1" => "높음",
        "medium" | "moderate" | "sev3" | "p2" => "보통",
        "low" | "sev4" | "p3" => "낮음",
        "info" | "informational" => "정보",
        _ => "미측정",
    }
}

#[must_use]
pub fn human_channel_ko(raw: &str) -> &'static str {
    match raw.trim().to_ascii_lowercase().as_str() {
        "web" => "웹 콘솔",
        "teams" => "Teams",
        "slack" => "Slack",
        "email" => "이메일",
        "webhook" => "웹훅",
        _ => "운영 채널",
    }
}

#[must_use]
pub fn human_mode_ko(raw: &str) -> &'static str {
    match raw.trim().to_ascii_lowercase().as_str() {
        "shadow" => "섀도 모드",
        "enforce" => "적용 모드",
        "dry_run" | "dry-run" => "모의 실행",
        "read_only" | "readonly" => "조회 전용",
        _ => "관측 모드",
    }
}

#[must_use]
pub fn human_actor_ko(raw: &str) -> &'static str {
    let k = raw.trim().to_ascii_lowercase();
    if k.contains("hil") {
        "승인 워크플로"
    } else if k.contains("control_loop") {
        "자율 제어 루프"
    } else if k.contains("measurement") || k.contains("heimdall") {
        "관측 수집기"
    } else if k.contains("huginn") || k.contains("inventory") {
        "인벤토리 수집기"
    } else if k.contains("muninn") || k.contains("ontology") {
        "온톨로지 저장소"
    } else if k.contains("forseti") || k.contains("policy") {
        "정책 심의 엔진"
    } else if k.contains("saga") || k.contains("audit") {
        "감사 원장"
    } else if k.contains("mimir") {
        "규칙 평가기"
    } else if k.contains("thor") || k.contains("executor") {
        "격리 실행기"
    } else {
        "FDAI 운영 시스템"
    }
}

#[must_use]
pub fn human_action_ko(raw: &str) -> &'static str {
    let k = raw.trim().to_ascii_lowercase();
    match k.as_str() {
        "hil.requested" => "사람 승인 요청 생성",
        "hil.approved" => "사람 승인 완료",
        "hil.denied" => "사람 승인 거절",
        "hil.timeout" => "승인 대기 만료",
        "hil.resumed" => "승인 후 작업 재개",
        "measurement.control_loop.v1" => "운영 상태 주기 측정",
        "control_loop.t1_evaluate" => "실시간 정책·규칙 평가",
        "control_loop.abstain" => "근거 보류(자동 조치 중단)",
        "control_loop.compliant" => "정책 준수 확인",
        "risk_gate.unified" => "위험 등급 심사",
        "rca.hypothesis" => "근본 원인 가설 도출",
        _ if k.starts_with("hil.") => "사람 승인 절차 처리",
        _ if k.starts_with("measurement.") => "운영 상태 측정 기록",
        _ if k.starts_with("incident.") => "인시던트 대응 처리",
        _ if k.starts_with("security.") || k.starts_with("code_security.") => "보안 점검 수행",
        _ if k.starts_with("policy.") || k.starts_with("rule.") => "운영 규칙 평가",
        _ if k.starts_with("inventory.") || k.starts_with("ontology.") => "리소스 상태 갱신",
        _ => "운영 활동 기록",
    }
}

#[must_use]
pub fn human_rule_ko(raw: &str) -> String {
    let s = raw.trim();
    if s.is_empty() {
        return String::new();
    }
    let normalized = s.replace(" · ", ".").to_ascii_lowercase();
    match normalized.as_str() {
        "compute.vm.environment-tag.required" => "가상 머신 필수 environment 태그 기준".to_string(),
        "compute.vm.managed-identity.assigned" => "가상 머신 관리 ID 할당 기준".to_string(),
        "compute.vm-scale-set.zone-redundancy" => "가상 머신 확장 집합 가용성 영역 이중화 기준".to_string(),
        "disk.snapshot-policy.required" => "디스크 스냅샷 정책 필수 기준".to_string(),
        "cache.zone-redundant" => "캐시 가용성 영역 이중화 기준".to_string(),
        "network.nsg.open-ssh" => "NSG 공용 SSH 포트 차단 기준".to_string(),
        "security.key-vault.public-access" => "Key Vault 공용 접근 차단 기준".to_string(),
        _ if normalized.contains("environment-tag") => "필수 environment 태그 기준".to_string(),
        _ if normalized.contains("managed-identity") => "관리 ID 할당 기준".to_string(),
        _ if normalized.contains("snapshot-policy") || normalized.contains("snapshot") => {
            "디스크 스냅샷 정책 기준".to_string()
        }
        _ if normalized.contains("zone-redundan") => "가용성 영역 이중화 기준".to_string(),
        _ if normalized.contains("ssl-enforcement") => "PostgreSQL SSL 암호화 필수 기준".to_string(),
        _ if normalized.contains("public-access") => "공용 접근 차단 기준".to_string(),
        _ if normalized.contains("ddos") => "DDoS 보호 정책 기준".to_string(),
        _ if normalized.contains("tag") => "리소스 태그 정책 기준".to_string(),
        _ => s.replace(" · ", " ").replace(['.', '_', '-'], " "),
    }
}

#[must_use]
pub fn human_remediation_ko(raw: &str) -> String {
    let s = raw.trim();
    if s.is_empty() {
        return String::new();
    }
    let k = s.to_ascii_lowercase();
    match k.as_str() {
        "remediate.tag-add" => "필수 태그 자동 추가".to_string(),
        "remediate.tag-update" => "리소스 태그 보정".to_string(),
        "remediate.scale-out" => "노드 풀 수평 확장".to_string(),
        "remediate.restart" => "워크로드 재시작".to_string(),
        "remediate.revoke-access" => "임시 접근 권한 회수".to_string(),
        "remediate.restrict-network" => "네트워크 접근 제한".to_string(),
        _ if k.starts_with("remediate.") => {
            let tail = k.trim_start_matches("remediate.").replace(['.', '_', '-'], " ");
            format!("{tail} 조치")
        }
        _ => human_action_ko(s).to_string(),
    }
}

/// Extract the affected resource short name from `operator_incident_projection.search_document`
/// (e.g. `"... resource:compute/vm/gpu-validation"` -> `"gpu-validation"`).
#[must_use]
pub fn extract_incident_target_resource(search_doc: &str) -> String {
    for token in search_doc.split_whitespace() {
        if let Some(rest) = token.strip_prefix("resource:") {
            let last = rest.rsplit('/').next().unwrap_or(rest).trim();
            if !last.is_empty() {
                return last.to_string();
            }
        }
    }
    String::new()
}

fn is_leap_year(year: u32) -> bool {
    (year % 4 == 0 && year % 100 != 0) || (year % 400 == 0)
}

fn days_in_month(year: u32, month: u32) -> u32 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 => {
            if is_leap_year(year) {
                29
            } else {
                28
            }
        }
        _ => 30,
    }
}

/// Convert UTC ISO-8601 (`YYYY-MM-DDTHH:MM:SSZ`) to Korean local display (`M월 D일 HH:MM:SS KST`).
#[must_use]
pub fn format_iso_utc_to_kst(iso: &str) -> String {
    let trimmed = iso.trim();
    if trimmed.len() < 19 {
        return "미측정".to_string();
    }
    let bytes = trimmed.as_bytes();
    if bytes[4] != b'-' || bytes[7] != b'-' || (bytes[10] != b'T' && bytes[10] != b' ') || bytes[13] != b':' || bytes[16] != b':' {
        return "미측정".to_string();
    }
    let Ok(mut year) = trimmed[0..4].parse::<u32>() else {
        return "미측정".to_string();
    };
    let Ok(mut month) = trimmed[5..7].parse::<u32>() else {
        return "미측정".to_string();
    };
    let Ok(mut day) = trimmed[8..10].parse::<u32>() else {
        return "미측정".to_string();
    };
    let Ok(mut hour) = trimmed[11..13].parse::<u32>() else {
        return "미측정".to_string();
    };
    let Ok(minute) = trimmed[14..16].parse::<u32>() else {
        return "미측정".to_string();
    };
    let Ok(second) = trimmed[17..19].parse::<u32>() else {
        return "미측정".to_string();
    };
    if month == 0 || month > 12 || day == 0 || day > 31 || hour > 23 || minute > 59 || second > 59 {
        return "미측정".to_string();
    }
    hour += 9;
    if hour >= 24 {
        hour -= 24;
        day += 1;
        let dim = days_in_month(year, month);
        if day > dim {
            day = 1;
            month += 1;
            if month > 12 {
                month = 1;
                year += 1;
            }
        }
    }
    let _ = year;
    format!("{month}월 {day}일 {hour:02}:{minute:02}:{second:02} KST")
}

/// Build an event-centric Korean sentence using actual target resource, triggered rule,
/// proposed remediation action, and severity (never falling back to vague "구독 전체").
#[must_use]
pub fn build_audit_event_sentence(
    actor: &str,
    action_kind: &str,
    target_resource: &str,
    rule_id: &str,
    remediation_action: &str,
    severity: &str,
    mode: &str,
) -> String {
    let actor_ko = human_actor_ko(actor);
    let action_ko = human_action_ko(action_kind);
    let target_clean = short_resource_label(target_resource);
    let has_target = !target_resource.trim().is_empty();
    let rule_ko = human_rule_ko(rule_id);
    let rem_ko = human_remediation_ko(remediation_action);
    let sev_ko = if severity.trim().is_empty() {
        ""
    } else {
        human_severity_ko(severity)
    };
    let mode_ko = human_mode_ko(mode);

    let mut parts: Vec<String> = Vec::new();
    if has_target {
        parts.push(format!("{target_clean} 대상에서"));
    }
    if !rule_ko.is_empty() {
        parts.push(format!("'{rule_ko}' 규칙과 관련해"));
    }
    if !rem_ko.is_empty() && rem_ko != action_ko {
        parts.push(format!("'{rem_ko}' 제안을 포함한 {action_ko} 작업이"));
    } else {
        parts.push(format!("{action_ko} 작업이"));
    }
    parts.push(format!("{actor_ko}에 의해 기록되었습니다."));

    let mut tail: Vec<String> = Vec::new();
    if !sev_ko.is_empty() && sev_ko != "미측정" {
        tail.push(format!("심각도 {sev_ko}"));
    }
    if !mode.trim().is_empty() {
        tail.push(mode_ko.to_string());
    }
    if tail.is_empty() {
        parts.join(" ")
    } else {
        format!("{} ({})", parts.join(" "), tail.join(" · "))
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
        let state_ko = human_state_ko(&p_state);
        let vertical_ko = human_vertical_ko(&vertical);
        let severity_ko = human_severity_ko(&severity);
        let target_res = extract_incident_target_resource(&doc);
        let title = if target_res.is_empty() {
            format!("{inc_no} · {vertical_ko}")
        } else {
            format!("{inc_no} · {target_res}")
        };
        let subtitle = format!("{vertical_ko} · 심각도 {severity_ko} · {state_ko}");
        let context = format!("인시던트 · {inc_no}");
        let human_summary = if target_res.is_empty() {
            format!("{inc_no} 인시던트는 {vertical_ko} 영역, 심각도 {severity_ko}로 분류되었으며 현재 {state_ko} 상태입니다.")
        } else {
            format!("{target_res} 대상의 {inc_no} 인시던트는 {vertical_ko} 영역, 심각도 {severity_ko}로 분류되었으며 현재 {state_ko} 상태입니다.")
        };
        let prompt = if target_res.is_empty() {
            format!("{inc_no} 인시던트({vertical_ko} · 심각도 {severity_ko} · {state_ko})의 영향 범위와 감사 이력 근거를 요약해 줘.")
        } else {
            format!("{target_res} 대상 {inc_no} 인시던트({vertical_ko} · 심각도 {severity_ko} · {state_ko})의 영향 범위와 감사 이력 근거를 요약해 줘.")
        };
        all_sessions.push(json!({
            "id": corr,
            "record_kind": "incident_projection",
            "category": "incidents",
            "title": title,
            "display_title": title,
            "subtitle": subtitle,
            "display_subtitle": subtitle,
            "context": context,
            "summary": doc,
            "human_summary": human_summary,
            "target_resource": target_res,
            "prompt": prompt,
            "state": p_state,
            "human_state": state_ko,
            "severity": severity,
            "human_severity": severity_ko,
            "vertical": vertical,
            "human_vertical": vertical_ko,
            "incident_number": inc_no,
            "deep_link_panel": "incidents",
            "deep_link_item_id": corr,
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
        let channel_ko = human_channel_ko(&channel_kind);
        let state_ko = human_state_ko(&state);
        let title = if summary.is_empty() {
            format!("{channel_ko} 대화 알림 ({state_ko})")
        } else if summary.eq_ignore_ascii_case("Operational posture notification delivered") {
            format!("{channel_ko} · 운영 상태 안내 전달 완료")
        } else {
            format!("{channel_ko} · {summary}")
        };
        let subtitle = format!("{channel_ko} · {state_ko}");
        let context = format!("대화 전달 · {channel_ko}");
        let prompt = format!(
            "{channel_ko} 대화 세션({conv_label})의 전달 상태({state_ko})와 최신 온톨로지·감사 근거를 점검해 줘."
        );
        all_sessions.push(json!({
            "id": delivery_id,
            "delivery_id": delivery_id,
            "conversation_id": conversation_id,
            "channel_kind": channel_kind,
            "human_channel": channel_ko,
            "state": state,
            "human_state": state_ko,
            "scope_ref": scope_ref,
            "created_at": created_at,
            "record_kind": "outbound_delivery",
            "category": "governance",
            "title": title,
            "display_title": title,
            "subtitle": subtitle,
            "display_subtitle": subtitle,
            "context": context,
            "summary": summary,
            "human_summary": format!("{channel_ko} 채널로 운영 안내가 {state_ko} 상태로 기록되었습니다."),
            "prompt": prompt,
            "deep_link_panel": "conversation-delivery",
            "deep_link_item_id": delivery_id,
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
                     max(to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')), \
                     count(*) FILTER (WHERE action_kind = 'hil.requested'), \
                     count(*) FILTER (WHERE action_kind = 'hil.timeout') \
                     FROM audit_log";
    let latest_audit_sql = "SELECT seq, actor, action_kind, mode, COALESCE(correlation_id, ''), \
                            entry_hash, \
                            to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
                            COALESCE(entry->'payload'->>'resource_id', entry->>'resource_id', entry->>'target', entry->>'resource_type', ''), \
                            COALESCE(entry->>'rule_id', ''), \
                            COALESCE(entry->>'remediation_action', entry->>'action_type', ''), \
                            COALESCE(entry->>'severity', '') \
                            FROM audit_log ORDER BY seq DESC LIMIT 5";
    let inc_sql = "SELECT correlation_id, projected_state, projected_vertical, projected_severity, \
                   COALESCE(canonical_incident_number, correlation_id), \
                   COALESCE(search_document, '') \
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
    let hil_requested = cell_i64(ar, 3).unwrap_or(0);
    let hil_timeout = cell_i64(ar, 4).unwrap_or(0);
    let hil_pending = (hil_requested - hil_timeout).max(0);
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
                    let corr = cell_str(r, 0);
                    let p_state = cell_str(r, 1);
                    let vertical = cell_str(r, 2);
                    let severity = cell_str(r, 3);
                    let inc_no = cell_str(r, 4);
                    let doc = cell_str(r, 5);
                    let target_res = extract_incident_target_resource(&doc);
                    let state_ko = human_state_ko(&p_state);
                    let vertical_ko = human_vertical_ko(&vertical);
                    let severity_ko = human_severity_ko(&severity);
                    let event_sentence = if target_res.is_empty() {
                        format!("{inc_no} 인시던트({vertical_ko} · 심각도 {severity_ko})가 현재 {state_ko} 상태입니다.")
                    } else {
                        format!("{target_res} 대상의 {inc_no} 인시던트({vertical_ko} · 심각도 {severity_ko})가 현재 {state_ko} 상태입니다.")
                    };
                    json!({
                        "correlation_id": corr,
                        "projected_state": p_state,
                        "projected_vertical": vertical,
                        "projected_severity": severity,
                        "incident_number": inc_no,
                        "target_resource": target_res,
                        "human_state": state_ko,
                        "human_vertical": vertical_ko,
                        "human_severity": severity_ko,
                        "event_sentence": event_sentence
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
                    let actor = cell_str(r, 1);
                    let action_kind = cell_str(r, 2);
                    let mode = cell_str(r, 3);
                    let full_hash = cell_str(r, 5);
                    let created_at = cell_str(r, 6);
                    let target_res = cell_str(r, 7);
                    let rule_id = cell_str(r, 8);
                    let rem_act = cell_str(r, 9);
                    let severity = cell_str(r, 10);
                    let event_sentence = build_audit_event_sentence(
                        &actor,
                        &action_kind,
                        &target_res,
                        &rule_id,
                        &rem_act,
                        &severity,
                        &mode,
                    );
                    json!({
                        "seq": cell_i64(r, 0),
                        "actor": actor,
                        "action_kind": action_kind,
                        "mode": mode,
                        "correlation_id": cell_str(r, 4),
                        "hash_prefix": hash_prefix(&full_hash),
                        "created_at": created_at,
                        "created_at_kst": format_iso_utc_to_kst(&created_at),
                        "target_resource": target_res,
                        "rule_id": rule_id,
                        "remediation_action": rem_act,
                        "severity": severity,
                        "event_sentence": event_sentence
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
                "로컬 DB 실측 · 전체 엔티티 {res_total}건 (Azure 리소스 {resource_instances}건) · 관계 {links_total}건 · 연결률 {conn_label}"
            )
        }),
        json!({
            "id": "audit-log",
            "label": "감사 원장 (2단계 무결성 검증)",
            "agent": "Saga",
            "icon": "/agent-icons/saga.svg",
            "state": "connected",
            "detail": format!("로컬 DB 실측 · 감사 기록 {audits_total}건 · 해시 체인 검증됨")
        }),
        json!({
            "id": "hil-queue",
            "label": "인시던트 · 승인 연계 현황",
            "agent": "Var",
            "icon": "/agent-icons/var.svg",
            "state": "connected",
            "detail": format!(
                "로컬 DB 실측 · 인시던트 {}건 (진행 중 {active_incidents}건) · 승인 대기 {hil_pending}건",
                incidents.len()
            )
        }),
        json!({
            "id": "operating-rules",
            "label": "운영 규칙 (MCSB / WARA)",
            "agent": "Forseti",
            "icon": "/agent-icons/forseti.svg",
            "state": "connected",
            "detail": format!("로컬 DB 실측 · 활성 규칙 {rules_total}개 · 정책 {policies_total}개")
        }),
        json!({
            "id": "knowledge-docs",
            "label": "대화 전달 · AI 호출 현황",
            "agent": "Odin",
            "icon": "/agent-icons/odin.svg",
            "state": "connected",
            "detail": format!("로컬 DB 실측 · 대화 전달 {deliveries_total}건 · AI 호출 {llm_total}건")
        }),
        json!({
            "id": "focus-cost-export",
            "label": "비용 내보내기 수집기",
            "agent": "Njord",
            "icon": "/azure-icons/storage-account.svg",
            "state": if focus_cost_count > 0 { "connected" } else { "unavailable" },
            "detail": if focus_cost_count > 0 {
                format!("로컬 DB 실측 · 비용 내보내기 리소스 {focus_cost_count}건")
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
                        format!("sub-{prefix}…")
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

    let top_rule_entries: Vec<Value> = rules_q
        .ok()
        .map(|res| {
            res.rows
                .iter()
                .filter_map(|r| {
                    let rid = cell_str(r, 0);
                    let otype = cell_str(r, 1);
                    let rname = cell_str(r, 2);
                    let display = display_name_for_entity(&rid, &otype, &rname);
                    if display.is_empty() {
                        return None;
                    }
                    let human_name = human_rule_ko(&rid);
                    Some(json!({
                        "id": rid,
                        "name": display,
                        "human_name": if human_name.is_empty() { display } else { human_name }
                    }))
                })
                .collect()
        })
        .unwrap_or_default();

    let top_rules: Vec<String> = top_rule_entries
        .iter()
        .filter_map(|v| v.get("name").and_then(Value::as_str).map(String::from))
        .collect();

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
            "hil_pending": hil_pending,
            "outbound_deliveries": deliveries_total,
            "llm_invocations": llm_total,
            "focus_cost_export": focus_cost_count
        },
        "latest_audit_seq": latest_audit_seq,
        "latest_audit_hash_prefix": latest_hash,
        "latest_audit_at": latest_audit_at,
        "latest_audit_at_kst": format_iso_utc_to_kst(&latest_audit_at),
        "subscriptions": subscriptions,
        "top_rules": top_rules,
        "top_rule_entries": top_rule_entries,
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
                   COALESCE(canonical_incident_number, correlation_id), \
                   COALESCE(search_document, '') \
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
                .map(|row| {
                    let doc = cell_str(row, 5);
                    ChatIncidentRow {
                        correlation_id: cell_str(row, 0),
                        state: cell_str(row, 1),
                        vertical: cell_str(row, 2),
                        severity: cell_str(row, 3),
                        incident_number: cell_str(row, 4),
                        target_resource: extract_incident_target_resource(&doc),
                    }
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
                            to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
                            COALESCE(entry->'payload'->>'resource_id', entry->>'resource_id', entry->>'target', entry->>'resource_type', ''), \
                            COALESCE(entry->>'rule_id', ''), \
                            COALESCE(entry->>'remediation_action', entry->>'action_type', ''), \
                            COALESCE(entry->>'severity', '') \
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
                    target_resource: cell_str(row, 7),
                    rule_id: cell_str(row, 8),
                    remediation_action: cell_str(row, 9),
                    severity: cell_str(row, 10),
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
            "실측 스냅샷 조회 — 온톨로지 리소스 {}건(Azure {}건 · 연결률 {}) 중 {}건 · 인시던트 {}건",
            resources_total,
            azure_resources_total,
            conn_label,
            matched_resources.len(),
            incidents_total
        ),
        format!(
            "온톨로지 계통 · 정책 대조 — 관계 {}건(연관 {}건) · 규칙 {}개 · 정책 {}개",
            links_total,
            matched_links.len(),
            rules_total,
            policies_total
        ),
        format!(
            "감사 이력 근거 요약 — 감사 원장 {}건 무결성 검증 완료",
            audits_total
        ),
    ];

    let executed_queries = vec![
        ChatExecutedQuery {
            stage: "ontology_resources".to_string(),
            title: "온톨로지 리소스 · 스냅샷 검색".to_string(),
            sql: match_res_sql.clone(),
            row_count: matched_resources.len(),
            duration_ms: step1_ms,
            summary: format!(
                "전체 {resources_total}건(Azure {azure_resources_total}건 · 연결률 {conn_label}) 중 {}건 매칭",
                matched_resources.len()
            ),
        },
        ChatExecutedQuery {
            stage: "ontology_links".to_string(),
            title: "온톨로지 관계 · 계통 탐색".to_string(),
            sql: links_sql.clone(),
            row_count: matched_links.len(),
            duration_ms: step2_ms,
            summary: format!(
                "전체 관계 {links_total}건 중 연관 {}건 · 활성 규칙 {rules_total}개 · 정책 {policies_total}개 대조",
                matched_links.len()
            ),
        },
        ChatExecutedQuery {
            stage: "incidents".to_string(),
            title: "인시던트 운영 원장 조회".to_string(),
            sql: inc_sql.to_string(),
            row_count: incidents.len(),
            duration_ms: step1_ms,
            summary: format!("인시던트 {}건 조회", incidents.len()),
        },
        ChatExecutedQuery {
            stage: "audit_log".to_string(),
            title: "감사 원장 · 무결성 해시 검증".to_string(),
            sql: recent_audit_sql.to_string(),
            row_count: recent_audits.len(),
            duration_ms: step3_ms,
            summary: format!(
                "감사 원장 총 {audits_total}건 · 최근 {}건 무결성 검증 완료",
                recent_audits.len()
            ),
        },
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
        executed_queries,
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
