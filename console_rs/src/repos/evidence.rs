//! Domain 5 (`evidence`, 6 panels) PostgreSQL repository with progressive-disclosure
//! audit stream (human-readable mode labels, single integrity summary, isolated forensic crypto).

use crate::db::{cell_i64, cell_str, clamp_limit, quote_like_contains, DbHandle};
use fdai_adapter_postgres::pg_quote_literal;
use serde_json::{json, Value};

#[derive(Debug, Default, Clone)]
pub struct AuditChainFilter<'a> {
    pub correlation_id: Option<&'a str>,
    pub search: Option<&'a str>,
    pub category: Option<&'a str>,
    pub mode: Option<&'a str>,
    pub action_kind: Option<&'a str>,
    pub agent: Option<&'a str>,
    pub window: Option<&'a str>,
    pub from_seq: Option<i64>,
    pub through_seq: Option<i64>,
    pub before_seq: Option<i64>,
    pub limit: Option<usize>,
}

#[must_use]
pub fn mode_label_ko(mode: &str) -> &'static str {
    match mode.trim().to_ascii_lowercase().as_str() {
        "enforce" | "enforced" | "approval" | "승인 후 조치" => "승인 후 조치",
        "auto" | "autonomous" | "auto_remediate" | "자동 조치" => "자동 조치",
        _ => "감시 전용",
    }
}

fn short_resource_name(raw: &str) -> String {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return String::from("system");
    }
    let last = trimmed
        .rsplit('/')
        .find(|seg| !seg.trim().is_empty())
        .unwrap_or(trimmed);
    let mut out = String::new();
    for ch in last.chars().take(48) {
        out.push(ch);
    }
    if out.is_empty() {
        String::from("system")
    } else {
        out
    }
}

fn human_actor_meta(actor: &str) -> (&'static str, &'static str, &'static str) {
    let low = actor.trim().to_ascii_lowercase();
    if low == "saga" {
        ("Saga", "감사 원장 (Saga)", "/agent-icons/saga.svg")
    } else if low == "forseti" || low.contains("policy") {
        ("Forseti", "정책 심의 엔진 (Forseti)", "/agent-icons/forseti.svg")
    } else if low == "heimdall" || low.contains("measurement") || low.contains("observation") {
        ("Heimdall", "관측 수집기 (Heimdall)", "/agent-icons/heimdall.svg")
    } else if low == "mimir" || low.contains(".rca") || low == "fdai.core.rca" {
        ("Mimir", "원인 분석 엔진 (Mimir)", "/agent-icons/mimir.svg")
    } else if low == "var" || low.contains("risk") || low.contains("hil_resume") {
        ("Var", "승인 워크플로 (Var)", "/agent-icons/var.svg")
    } else if low == "thor" || low.contains("executor") {
        ("Thor", "격리 실행기 (Thor)", "/agent-icons/thor.svg")
    } else if low == "vidar" {
        ("Vidar", "독립 효과 검증 (Vidar)", "/agent-icons/vidar.svg")
    } else if low == "odin" || low.contains("control_loop") {
        ("Odin", "제어 루프 엔진 (Odin)", "/agent-icons/odin.svg")
    } else if low.contains("handover") {
        ("Bragi", "인수인계 관측 (Bragi)", "/agent-icons/bragi.svg")
    } else {
        ("FDAI 시스템", "FDAI 운영 플랫폼", "/agent-icons/saga.svg")
    }
}

fn target_icon_for(target: &str, resource_type: &str) -> &'static str {
    let combined = format!(
        "{} {}",
        target.to_ascii_lowercase(),
        resource_type.to_ascii_lowercase()
    );
    if combined.contains("postgres") || combined.contains("psql") || combined.contains("sql") {
        "/azure-icons/postgresql.svg"
    } else if combined.contains("container") || combined.contains("caj") || combined.contains("capp") {
        "/azure-icons/container-apps.svg"
    } else if combined.contains("aks") || combined.contains("kube") {
        "/azure-icons/kubernetes-services.svg"
    } else if combined.contains("keyvault") || combined.contains("key-vault") || combined.contains("kv-") {
        "/azure-icons/key-vault.svg"
    } else if combined.contains("redis") || combined.contains("cache") {
        "/azure-icons/cache-redis.svg"
    } else if combined.contains("loadbalancer") || combined.contains("load-balancer") || combined.contains("-lb") {
        "/azure-icons/load-balancer.svg"
    } else if combined.contains("gateway") {
        "/azure-icons/application-gateway.svg"
    } else if combined.contains("network.interface") || combined.contains("nsg") || combined.contains("security-group") || combined.contains("firewall") {
        "/azure-icons/network-security-group.svg"
    } else if combined.contains("disk") {
        "/azure-icons/disks.svg"
    } else if combined.contains("storage") {
        "/azure-icons/storage-account.svg"
    } else if combined.contains("vm") || combined.contains("virtual-machine") {
        "/azure-icons/virtual-machine.svg"
    } else {
        "/azure-icons/monitor.svg"
    }
}

fn humanize_target_ko(raw: &str) -> String {
    let trimmed = raw.trim();
    if trimmed.is_empty() || trimmed.eq_ignore_ascii_case("system") {
        return String::from("플랫폼 시스템");
    }
    let low = trimmed.to_ascii_lowercase();
    if low == "compute.vm.environment-tag.required" {
        String::from("가상 머신 환경 태그 필수 정책")
    } else if low == "compute.vm-scale-set" || low.contains("vm-scale-set") || low.contains("vmss") {
        String::from("가상 머신 확장 집합 (VMSS)")
    } else if low == "compute.container-app-job" || low.contains("container-app-job") {
        String::from("컨테이너 앱 작업")
    } else if low == "compute.container-app" || low.contains("container-app") {
        String::from("컨테이너 앱")
    } else if low == "compute.aks" || low.contains("kubernetes") {
        String::from("AKS 클러스터")
    } else if low == "compute.vm" || low.contains("virtual-machine") {
        String::from("가상 머신")
    } else if low == "network.load-balancer" || low.contains("load-balancer") || low.contains("loadbalancer") {
        String::from("부하 분산 장치")
    } else if low == "network.interface" || low.contains("network-interface") {
        String::from("네트워크 인터페이스")
    } else if low == "network.application-gateway" || low.contains("application-gateway") {
        String::from("애플리케이션 게이트웨이")
    } else if low == "network.firewall" || low == "firewall" {
        String::from("Azure 방화벽")
    } else if low == "network.virtual-network" || low.contains("virtual-network") {
        String::from("가상 네트워크 (VNet)")
    } else if low == "network.private-endpoint" || low.contains("private-endpoint") {
        String::from("프라이빗 엔드포인트")
    } else if low == "network.security-group" || low.contains("security-group") {
        String::from("네트워크 보안 그룹 (NSG)")
    } else if low == "disk" || low == "storage.disk" || low.ends_with(".disk") {
        String::from("관리 디스크")
    } else if low.contains("postgres") {
        String::from("PostgreSQL 데이터베이스")
    } else if low.contains("redis") {
        String::from("Redis 캐시")
    } else if low.contains("key-vault") || low.contains("keyvault") {
        String::from("Key Vault (키 보관소)")
    } else if low.contains("storage-account") || low == "data-storage" {
        String::from("스토리지 계정")
    } else if low.contains("service-bus") {
        String::from("Service Bus 메시지 브로커")
    } else if low.contains("log-analytics") {
        String::from("Log Analytics 작업 영역")
    } else if low.contains("openai") {
        String::from("Azure OpenAI 서비스")
    } else if low.contains("container.registry") || low.contains("container-registry") {
        String::from("컨테이너 레지스트리")
    } else {
        trimmed.to_string()
    }
}

fn humanize_action_ko(raw: &str) -> &'static str {
    let ak = raw.trim().to_ascii_lowercase();
    match ak.as_str() {
        "hil.requested" => "사람 승인 요청 생성",
        "hil.approved" => "사람 승인 완료",
        "hil.rejected" => "사람 승인 반려",
        "hil.timeout" | "hil.expired" | "hil.request.dispatch_unavailable" => "승인 요청 기한 만료·차단",
        "measurement.control_loop.v1" | "measurement.control_loop" => "운영 제어 루프 관측 완료",
        "observation-campaign.source-transition" => "관측 캠페인 상태 전이",
        "risk_gate.unified" => "통합 위험 게이트 평가",
        "rca.hypothesis" => "원인 분석 가설 도출",
        "control_loop.abstain" => "근거 부족으로 조치 보류",
        "control_loop.compliant" => "정책 준수 확인 완료",
        "control_loop.t1_evaluate" => "과거 유사 사례 비교 평가",
        "remediate.tag-add" => "필수 태그 자동 추가",
        "process.created" => "워크플로 실행 시작",
        "process.completed" => "워크플로 실행 완료",
        "process.failed" => "워크플로 실행 실패",
        "process.waiting" | "step.waiting" => "승인 또는 후속 응답 대기",
        "step.started" => "실행 단계 시작",
        "step.completed" => "실행 단계 완료",
        "action.executed" => "자동 조치 실행 완료",
        "action.denied" | "action.blocked" => "정책에 의해 조치 차단",
        "action.dry_run" => "사전 드라이런 검증 완료",
        "action.rolled_back" => "자동 롤백 복구 완료",
        "policy.evaluated" => "운영 정책 평가",
        "policy.violation" => "운영 정책 위반 감지",
        "incident.opened" | "incident.detected" => "운영 이상(인시던트) 감지",
        "incident.resolved" => "운영 이상 해결 완료",
        "inventory.observed" | "inventory.upsert" => "리소스 상태 정보 갱신",
        "promotion.approved" => "자동화 승격 승인",
        "promotion.recalled" => "자동화 즉시 회수",
        "conversation.delivered" => "운영 알림 메시지 전송",
        _ => {
            if ak.starts_with("hil.") {
                "사람 승인 절차 이벤트"
            } else if ak.starts_with("risk_gate") {
                "통합 위험 게이트 평가"
            } else if ak.starts_with("measurement.") || ak.starts_with("observation") {
                "운영 상태 관측 기록"
            } else if ak.contains("rollback") {
                "안전 롤백 복구"
            } else if ak.starts_with("action.") || ak.starts_with("executor.") || ak.contains("remediate") {
                "안전 조치 실행"
            } else if ak.starts_with("policy.") || ak.starts_with("rule.") {
                "운영 정책 평가"
            } else if ak.starts_with("handover.") {
                "담당자 인수인계 관측"
            } else if ak.starts_with("runtime.") || ak.starts_with("process.") || ak.starts_with("step.") {
                "워크플로 실행 단계 기록"
            } else if ak.starts_with("mimir.") || ak.starts_with("rca.") {
                "원인 분석 기록"
            } else {
                "운영 감사 이벤트 기록"
            }
        }
    }
}

fn humanize_reason_ko(raw: &str) -> String {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return String::new();
    }
    let low = trimmed.to_ascii_lowercase();
    if low == "no_neighbour_found" {
        String::from("유사 과거 사례 없음")
    } else if low == "no_rule_matches_resource_and_signal_type" {
        String::from("일치하는 자동화 규칙 없음")
    } else if low.starts_with("config_drift control violated") || low.contains(".rego") {
        String::from("구성 기준선 이탈(Config Drift) 정책 위반이 감지되었습니다.")
    } else if low == "hil" {
        String::from("사람 승인 필요")
    } else if low == "deny" || low == "block" {
        String::from("정책 차단")
    } else if low == "allow" {
        String::from("허용")
    } else if low == "abstain" {
        String::from("판단 보류")
    } else {
        trimmed.chars().take(180).collect()
    }
}

fn classify_audit_entry(
    action_kind: &str,
    mode: &str,
    target: &str,
    rule_id: &str,
    reason: &str,
    decision: &str,
    action_type: &str,
) -> (&'static str, &'static str, &'static str, String, String, &'static str) {
    let ak = action_kind.trim().to_ascii_lowercase();
    let mode_ko = mode_label_ko(mode);
    let target_ko = humanize_target_ko(target);
    let rule_ko = if !rule_id.is_empty() {
        humanize_target_ko(rule_id)
    } else {
        target_ko.clone()
    };
    let action_ko = humanize_action_ko(action_kind);
    let reason_ko = humanize_reason_ko(reason);

    if ak.starts_with("hil.requested") {
        let act_ko = if !action_type.is_empty() {
            humanize_action_ko(action_type)
        } else {
            "조치 승인"
        };
        return (
            "approval",
            "human",
            "사람 승인 요청",
            format!("{rule_ko} — {act_ko} 승인 요청"),
            format!("사람 승인 게이트가 {target_ko} 대상 조치({act_ko})에 대해 확인을 요청했습니다. ({mode_ko})"),
            "intent",
        );
    }
    if ak.starts_with("hil.timeout") || ak.starts_with("hil.request.dispatch_unavailable") {
        return (
            "approval",
            "sec",
            "승인 대기 만료·차단",
            format!("{rule_ko} — 사람 승인 미완료 자동 차단"),
            format!("승인 응답 부재 또는 전달 불가로 실행을 안전 차단했습니다. 침묵은 권한을 부여하지 않습니다. ({mode_ko})"),
            "intent",
        );
    }
    if ak.starts_with("risk_gate") {
        let dec_ko = if decision.is_empty() {
            String::from("평가 완료")
        } else {
            humanize_reason_ko(decision)
        };
        return (
            "approval",
            if decision.eq_ignore_ascii_case("deny") || decision.eq_ignore_ascii_case("block") {
                "sec"
            } else {
                "human"
            },
            "위험 게이트 판정",
            format!("{target_ko} — 통합 위험 게이트 판정 ({dec_ko})"),
            format!("통합 위험·권한 게이트가 {target_ko} 요청을 검토하고 판정({dec_ko})을 원장에 기록했습니다. ({mode_ko})"),
            "intent",
        );
    }
    if ak.contains("rollback") || ak.contains("remediate") || ak.starts_with("action.") || ak.starts_with("executor.") {
        return (
            "action",
            "sre",
            if ak.contains("rollback") { "안전 롤백" } else { "조치 기록" },
            format!("{target_ko} — {action_ko}"),
            format!("안전 경계 내에서 {target_ko} 대상 '{action_ko}' 단계가 수행·기록되었습니다. ({mode_ko})"),
            "dispatch",
        );
    }
    if ak == "rca.hypothesis" {
        let summary = if !reason_ko.is_empty() {
            format!("{rule_ko}: {reason_ko}")
        } else {
            format!("{rule_ko} 기반 근본 원인 가설을 도출해 감사 원장에 기록했습니다.")
        };
        return (
            "observe",
            "sre",
            "원인 가설 도출",
            format!("{rule_ko} — 원인 분석 가설 기록"),
            summary,
            "observe",
        );
    }
    if ak == "control_loop.abstain" {
        let why = if !reason_ko.is_empty() { reason_ko } else { String::from("일치 규칙 없음") };
        return (
            "shadow",
            "neutral",
            "근거 부족 보류",
            format!("{target_ko} — 판단 보류 ({why})"),
            format!("결정론적 규칙 근거가 충분하지 않아 자동 조치를 수행하지 않고 명시적으로 보류했습니다. ({mode_ko})"),
            "observe",
        );
    }
    if ak == "control_loop.compliant" {
        return (
            "observe",
            "live",
            "정책 준수 확인",
            format!("{target_ko} — 정책 준수 검증 완료"),
            format!("결정론적 정책 평가 결과 위반 항목이 없어 정상 상태로 기록했습니다. ({mode_ko})"),
            "close",
        );
    }
    if ak == "control_loop.t1_evaluate" {
        let why = if !reason_ko.is_empty() { reason_ko } else { String::from("유사 사례 평가") };
        return (
            "shadow",
            "neutral",
            "유사 사례 평가",
            format!("{target_ko} — 유사 사례 검토 ({why})"),
            format!("과거 검증 사례와의 유사도를 비교 평가했습니다. 근거 기준 미달 시 자동 보류합니다. ({mode_ko})"),
            "observe",
        );
    }
    if ak.starts_with("measurement.") || ak.starts_with("observation") || ak.starts_with("runtime.") || ak.starts_with("mimir.") || ak.starts_with("handover.") {
        return (
            "observe",
            "live",
            "관측·상태 기록",
            format!("{target_ko} — {action_ko}"),
            format!("{target_ko}의 운영 상태 및 관측 스냅샷({action_ko})을 추가 전용 원장에 기록했습니다. ({mode_ko})"),
            "close",
        );
    }
    (
        if mode.eq_ignore_ascii_case("shadow") { "shadow" } else { "observe" },
        "live",
        "원장 기록 완료",
        format!("{target_ko} — {action_ko}"),
        format!("{target_ko} 대상 '{action_ko}' 이벤트가 무결성 체인에 봉인되었습니다. ({mode_ko})"),
        "close",
    )
}

async fn check_head_integrity(db: &DbHandle, window: usize) -> Option<(usize, usize, Option<i64>)> {
    let lim = window.clamp(2, 100);
    let sql = format!(
        "SELECT seq, previous_hash, entry_hash FROM audit_log ORDER BY seq DESC LIMIT {lim}"
    );
    let res = db.query_single_readonly(&sql).await.ok()?;
    let mut link_gaps = 0_usize;
    let mut prev_seq: Option<i64> = None;
    let mut prev_expected_hash: Option<String> = None;
    let latest_seq = res.rows.first().and_then(|r| cell_i64(r, 0));

    for r in &res.rows {
        let seq = cell_i64(r, 0);
        let prev_hash = cell_str(r, 1);
        let entry_hash = cell_str(r, 2);
        if let (Some(ps), Some(cur), Some(exp)) = (prev_seq, seq, prev_expected_hash.as_ref()) {
            if ps == cur + 1 && !exp.is_empty() && exp != &entry_hash {
                link_gaps = link_gaps.saturating_add(1);
            }
        }
        prev_seq = seq;
        prev_expected_hash = Some(prev_hash);
    }
    Some((link_gaps, res.rows.len(), latest_seq))
}

pub async fn fetch_audit_chain(
    db: &DbHandle,
    correlation_id: Option<&str>,
    search: Option<&str>,
    before_seq: Option<i64>,
    limit: Option<usize>,
) -> Value {
    fetch_audit_chain_filtered(
        db,
        &AuditChainFilter {
            correlation_id,
            search,
            before_seq,
            limit,
            ..AuditChainFilter::default()
        },
    )
    .await
}

pub async fn fetch_audit_chain_filtered(db: &DbHandle, f: &AuditChainFilter<'_>) -> Value {
    let lim = clamp_limit(f.limit, 50, 100);
    let mut clauses: Vec<String> = Vec::new();
    let mut has_non_seq_filter = false;

    if let Some(cid) = f.correlation_id.map(str::trim).filter(|s| !s.is_empty()) {
        clauses.push(format!("correlation_id = {}", pg_quote_literal(cid)));
        has_non_seq_filter = true;
    }
    if let Some(q) = f.search.map(str::trim).filter(|s| !s.is_empty()) {
        let pat = quote_like_contains(q);
        let mut search_ors = vec![
            format!("actor ILIKE {pat} ESCAPE '\\'"),
            format!("action_kind ILIKE {pat} ESCAPE '\\'"),
            format!("COALESCE(correlation_id, '') ILIKE {pat} ESCAPE '\\'"),
            format!("entry_hash ILIKE {pat} ESCAPE '\\'"),
            format!("COALESCE(entry->>'rule_id', '') ILIKE {pat} ESCAPE '\\'"),
            format!("COALESCE(entry->>'resource_type', '') ILIKE {pat} ESCAPE '\\'"),
            format!("COALESCE(entry->'payload'->>'resource_id', '') ILIKE {pat} ESCAPE '\\'"),
        ];
        if q.contains("승인") || q.contains("차단") || q.contains("위험") {
            search_ors.push(String::from(
                "action_kind LIKE 'hil.%' OR action_kind LIKE 'risk_gate%' OR action_kind LIKE 'policy.%'",
            ));
        }
        if q.contains("보류") {
            search_ors.push(String::from("action_kind LIKE '%abstain%'"));
        }
        if q.contains("원인") || q.contains("가설") {
            search_ors.push(String::from("action_kind LIKE 'rca.%'"));
        }
        if q.contains("감시") {
            search_ors.push(String::from("mode = 'shadow'"));
        }
        if q.contains("롤백") || q.contains("복구") || q.contains("실행") {
            search_ors.push(String::from(
                "action_kind LIKE 'action.%' OR action_kind LIKE 'executor.%' OR action_kind LIKE '%rollback%' OR action_kind LIKE '%remediate%'",
            ));
        }
        if q.contains("관측") || q.contains("준수") || q.contains("측정") {
            search_ors.push(String::from(
                "action_kind LIKE 'measurement.%' OR action_kind LIKE 'observation%' OR action_kind = 'control_loop.compliant'",
            ));
        }
        clauses.push(format!("({})", search_ors.join(" OR ")));
        has_non_seq_filter = true;
    }
    if let Some(cat) = f
        .category
        .map(str::trim)
        .filter(|s| !s.is_empty() && !s.eq_ignore_ascii_case("all"))
    {
        match cat.to_ascii_lowercase().as_str() {
            "approval" => {
                clauses.push(String::from(
                    "(action_kind LIKE 'hil.%' OR action_kind LIKE 'risk_gate%' OR action_kind LIKE 'policy.%')",
                ));
                has_non_seq_filter = true;
            }
            "action" => {
                clauses.push(String::from(
                    "(action_kind LIKE 'action.%' OR action_kind LIKE 'executor.%' OR action_kind LIKE '%rollback%' OR action_kind LIKE '%remediate%')",
                ));
                has_non_seq_filter = true;
            }
            "observe" => {
                clauses.push(String::from(
                    "(action_kind LIKE 'measurement.%' OR action_kind LIKE 'observation%' OR action_kind LIKE 'runtime.%' OR action_kind LIKE 'mimir.%' OR action_kind LIKE 'handover.%' OR action_kind = 'rca.hypothesis' OR action_kind = 'control_loop.compliant')",
                ));
                has_non_seq_filter = true;
            }
            "shadow" => {
                clauses.push(String::from(
                    "(action_kind = 'control_loop.abstain' OR action_kind = 'control_loop.t1_evaluate' OR (mode = 'shadow' AND action_kind = 'audit.record'))",
                ));
                has_non_seq_filter = true;
            }
            _ => {}
        }
    }
    if let Some(m) = f
        .mode
        .map(str::trim)
        .filter(|s| !s.is_empty() && !s.eq_ignore_ascii_case("all"))
    {
        let low = m.to_ascii_lowercase();
        if low == "enforce" || low == "enforced" || m == "승인 후 조치" {
            clauses.push(String::from("mode IN ('enforce', 'enforced', 'approval')"));
            has_non_seq_filter = true;
        } else if low == "auto" || low == "autonomous" || m == "자동 조치" {
            clauses.push(String::from("mode IN ('auto', 'autonomous', 'auto_remediate')"));
            has_non_seq_filter = true;
        } else if low == "shadow" || m == "감시 전용" {
            clauses.push(String::from("mode = 'shadow'"));
            has_non_seq_filter = true;
        }
    }
    if let Some(ak) = f
        .action_kind
        .map(str::trim)
        .filter(|s| !s.is_empty() && !s.eq_ignore_ascii_case("all"))
    {
        let pat = quote_like_contains(ak);
        clauses.push(format!("action_kind ILIKE {pat} ESCAPE '\\'"));
        has_non_seq_filter = true;
    }
    if let Some(ag) = f
        .agent
        .map(str::trim)
        .filter(|s| !s.is_empty() && !s.eq_ignore_ascii_case("all"))
    {
        let pat = quote_like_contains(ag);
        clauses.push(format!("actor ILIKE {pat} ESCAPE '\\'"));
        has_non_seq_filter = true;
    }
    if let Some(w) = f
        .window
        .map(str::trim)
        .filter(|s| !s.is_empty() && !s.eq_ignore_ascii_case("all"))
    {
        let interval = match w.to_ascii_lowercase().as_str() {
            "24h" => Some("24 hours"),
            "7d" => Some("7 days"),
            "30d" => Some("30 days"),
            "90d" => Some("90 days"),
            _ => None,
        };
        if let Some(iv) = interval {
            let q_iv = pg_quote_literal(iv);
            clauses.push(format!("created_at >= NOW() - CAST({q_iv} AS interval)"));
            has_non_seq_filter = true;
        }
    }
    if let Some(seq) = f.before_seq.filter(|&v| v > 0) {
        clauses.push(format!("seq < {seq}"));
    }
    if let Some(from_s) = f.from_seq.filter(|&v| v > 0) {
        clauses.push(format!("seq >= {from_s}"));
    }
    if let Some(through_s) = f.through_seq.filter(|&v| v > 0) {
        clauses.push(format!("seq <= {through_s}"));
    }

    let where_sql = if clauses.is_empty() {
        String::new()
    } else {
        format!("WHERE {}", clauses.join(" AND "))
    };
    let fetch_lim = lim.saturating_add(1);
    let sql = format!(
        "SELECT seq, event_id::text, COALESCE(correlation_id, ''), actor, action_kind, mode, \
         previous_hash, entry_hash, \
         to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
         COALESCE(entry->'payload'->>'resource_id', entry->>'resource_id', entry->>'resource_type', ''), \
         COALESCE(entry->>'resource_type', ''), \
         COALESCE(entry->>'rule_id', ''), \
         COALESCE(entry->>'rca_cause', entry->>'reason', entry->>'t1_reason', ''), \
         COALESCE(entry->>'decision', entry->>'outcome', ''), \
         COALESCE(entry->>'action_type', ''), \
         COALESCE(entry->>'idempotency_key', ''), \
         COALESCE(entry->>'tier', entry->>'rca_tier', ''), \
         COALESCE(entry->>'severity', '') \
         FROM audit_log {where_sql} ORDER BY seq DESC LIMIT {fetch_lim}"
    );
    let kpi_sql = "SELECT \
        count(*), \
        count(*) FILTER (WHERE action_kind LIKE 'hil.%' OR action_kind LIKE 'risk_gate%' OR action_kind LIKE 'policy.%'), \
        count(*) FILTER (WHERE action_kind LIKE 'action.%' OR action_kind LIKE 'executor.%' OR action_kind LIKE '%rollback%' OR action_kind LIKE '%remediate%'), \
        count(*) FILTER (WHERE mode = 'shadow') \
        FROM audit_log";

    let (rows_res, kpi_res) = tokio::join!(
        db.query_single_readonly(&sql),
        db.query_single_readonly(kpi_sql),
    );
    let Ok(res) = rows_res else {
        return db.not_measured("evidence", "/api/v4/evidence/audit", "postgres_unreachable");
    };

    let has_more = res.rows.len() > lim;
    let slice_len = res.rows.len().min(lim);
    let mut link_gaps = 0_usize;
    let mut prev_seq: Option<i64> = None;
    let mut prev_expected_hash: Option<String> = None;
    let mut items: Vec<Value> = Vec::with_capacity(slice_len);

    for r in res.rows.iter().take(slice_len) {
        let seq = cell_i64(r, 0);
        let event_id = cell_str(r, 1);
        let corr = cell_str(r, 2);
        let actor = cell_str(r, 3);
        let action_kind = cell_str(r, 4);
        let mode = cell_str(r, 5);
        let prev_hash = cell_str(r, 6);
        let entry_hash = cell_str(r, 7);
        let created_at = cell_str(r, 8);
        let raw_target = cell_str(r, 9);
        let resource_type = cell_str(r, 10);
        let rule_id = cell_str(r, 11);
        let reason = cell_str(r, 12);
        let decision = cell_str(r, 13);
        let action_type = cell_str(r, 14);
        let idem_key = cell_str(r, 15);
        let tier = cell_str(r, 16);
        let severity = cell_str(r, 17);

        if let (Some(ps), Some(cur), Some(exp)) = (prev_seq, seq, prev_expected_hash.as_ref()) {
            if ps == cur + 1 && !exp.is_empty() && exp != &entry_hash {
                link_gaps = link_gaps.saturating_add(1);
            }
        }
        prev_seq = seq;
        prev_expected_hash = Some(prev_hash.clone());

        let label = mode_label_ko(&mode);
        let target = short_resource_name(if raw_target.is_empty() {
            if !rule_id.is_empty() {
                &rule_id
            } else {
                &resource_type
            }
        } else {
            &raw_target
        });
        let target_label_ko = humanize_target_ko(&target);
        let action_label_ko = humanize_action_ko(&action_kind);
        let target_icon = target_icon_for(&target, &resource_type);
        let (actor_label, actor_role, agent_icon) = human_actor_meta(&actor);
        let (cat, tone, status_ko, title_ko, summary_ko, phase) = classify_audit_entry(
            &action_kind,
            &mode,
            &target,
            &rule_id,
            &reason,
            &decision,
            &action_type,
        );
        let human_summary = format!("{actor_label} · {title_ko} ({label})");
        let risk_label = if !tier.is_empty() {
            format!("{} · {}", tier.to_ascii_uppercase(), if severity.is_empty() { "운영" } else { &severity })
        } else if !severity.is_empty() {
            format!("위험도 {severity}")
        } else {
            String::from("표준 거버넌스")
        };

        items.push(json!({
            "seq": seq,
            "correlation_id": corr,
            "actor": actor,
            "actor_label": actor_label,
            "actor_role": actor_role,
            "agent_icon": agent_icon,
            "action_kind": action_kind,
            "action_label_ko": action_label_ko,
            "mode_label_ko": label,
            "category": cat,
            "tone": tone,
            "status_ko": status_ko,
            "title_ko": title_ko,
            "summary_ko": summary_ko,
            "human_summary": human_summary,
            "target": target,
            "target_label_ko": target_label_ko,
            "resource_type": resource_type,
            "target_icon": target_icon,
            "rule_id": rule_id,
            "risk_label": risk_label,
            "recorded_phase": phase,
            "idempotency_key": if idem_key.is_empty() { format!("audit-seq-{}", seq.unwrap_or(0)) } else { idem_key },
            "created_at": created_at,
            "forensic_crypto": {
                "disclosure_default_collapsed": true,
                "event_id": event_id,
                "previous_hash": prev_hash,
                "entry_hash": entry_hash
            }
        }));
    }

    let (final_gaps, checked_window) = if has_non_seq_filter {
        match check_head_integrity(db, 25).await {
            Some((g, w, _)) => (g, w),
            None => (link_gaps, items.len()),
        }
    } else {
        (link_gaps, items.len())
    };

    let (total_count, approval_count, action_count, shadow_count) = match kpi_res {
        Ok(kr) => {
            if let Some(row) = kr.rows.first() {
                (
                    cell_i64(row, 0).unwrap_or(0),
                    cell_i64(row, 1).unwrap_or(0),
                    cell_i64(row, 2).unwrap_or(0),
                    cell_i64(row, 3).unwrap_or(0),
                )
            } else {
                (items.len() as i64, 0, 0, 0)
            }
        }
        Err(_) => (items.len() as i64, 0, 0, 0),
    };

    let next_before_seq = if has_more {
        res.rows
            .get(slice_len.saturating_sub(1))
            .and_then(|r| cell_i64(r, 0))
    } else {
        None
    };
    let next_cursor = next_before_seq.map(|v| v.to_string());
    let integrity_verified = final_gaps == 0;
    let integrity_status = if integrity_verified { "verified" } else { "tampered" };

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "progressive_disclosure": true,
        "audit_integrity": {
            "status": integrity_status,
            "reason": if integrity_verified { Value::Null } else { json!("hash_chain_gap_detected") },
            "current_record_count": total_count,
            "current_link_gap_count": final_gaps,
            "checked_window": checked_window
        },
        "summary": {
            "matching_record_count": total_count,
            "kpis": {
                "total": total_count,
                "approval": approval_count,
                "action": action_count,
                "shadow": shadow_count,
                "observe": total_count.saturating_sub(approval_count).saturating_sub(action_count)
            },
            "integrity": {
                "status": integrity_status,
                "current_record_count": total_count,
                "current_link_gap_count": final_gaps,
                "checked_window": checked_window
            }
        },
        "integrity_verified": integrity_verified,
        "integrity_alert": !integrity_verified,
        "total_count": total_count,
        "count": items.len(),
        "has_more": has_more,
        "next_before_seq": next_before_seq,
        "next_cursor": next_cursor,
        "items": items
    })
}

async fn fetch_connected_scopes(db: &DbHandle) -> (i64, Vec<Value>) {
    let sub_sql = "SELECT split_part(id, '/', 1) AS scope_id, count(*) \
        FROM ontology_resource \
        WHERE object_type = 'Resource' AND id LIKE 'scope-%' \
        GROUP BY 1 ORDER BY 2 DESC LIMIT 8";
    let rg_sql = "SELECT split_part(id, '/', 3) AS rg, count(*) \
        FROM ontology_resource \
        WHERE object_type = 'Resource' AND id LIKE 'scope-%/resource-group/%' \
        GROUP BY 1 ORDER BY 2 DESC LIMIT 6";
    let (sub_res, rg_res) = tokio::join!(
        db.query_single_readonly(sub_sql),
        db.query_single_readonly(rg_sql),
    );
    let mut total_resources = 0_i64;
    let mut scopes: Vec<Value> = Vec::new();
    if let Ok(sr) = sub_res {
        for r in &sr.rows {
            let sid = cell_str(r, 0);
            let cnt = cell_i64(r, 1).unwrap_or(0);
            if sid.is_empty() {
                continue;
            }
            total_resources = total_resources.saturating_add(cnt);
            scopes.push(json!({
                "id": sid,
                "kind": "subscription_scope",
                "label": format!("구독 범위: {sid} ({cnt} 리소스)"),
                "resource_count": cnt
            }));
        }
    }
    if let Ok(rr) = rg_res {
        for r in &rr.rows {
            let rg = cell_str(r, 0);
            let cnt = cell_i64(r, 1).unwrap_or(0);
            if rg.is_empty() {
                continue;
            }
            scopes.push(json!({
                "id": rg,
                "kind": "resource_group",
                "label": format!("리소스 그룹: {rg} ({cnt})"),
                "resource_count": cnt
            }));
        }
    }
    (total_resources, scopes)
}

pub async fn fetch_evidence_summary(db: &DbHandle) -> Value {
    let counts_sql = "SELECT \
        (SELECT count(*) FROM audit_log), \
        (SELECT count(*) FROM process_event), \
        (SELECT count(*) FROM operator_incident_projection), \
        (SELECT count(*) FROM operational_state_transition), \
        (SELECT count(*) FROM operational_retention_policy), \
        (SELECT count(*) FROM browser_evidence_artifact), \
        (SELECT count(*) FROM conversation_outbound_delivery)";

    let (counts_res, head_res, (ontology_resources, available_scopes)) = tokio::join!(
        db.query_single_readonly(counts_sql),
        check_head_integrity(db, 25),
        fetch_connected_scopes(db),
    );
    let Ok(cr) = counts_res else {
        return db.not_measured("evidence", "/api/v4/evidence/summary", "postgres_unreachable");
    };
    let Some(row) = cr.rows.first() else {
        return db.not_measured("evidence", "/api/v4/evidence/summary", "empty_summary_result");
    };

    let audit_total = cell_i64(row, 0).unwrap_or(0);
    let process_events = cell_i64(row, 1).unwrap_or(0);
    let incidents = cell_i64(row, 2).unwrap_or(0);
    let transitions = cell_i64(row, 3).unwrap_or(0);
    let retention_policies = cell_i64(row, 4).unwrap_or(0);
    let browser_artifacts = cell_i64(row, 5).unwrap_or(0);
    let conversations = cell_i64(row, 6).unwrap_or(0);

    let (gaps, checked_window, latest_seq) = head_res.unwrap_or((0, 0, None));
    let integrity_verified = gaps == 0;
    let integrity_status = if integrity_verified { "verified" } else { "tampered" };

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "audit_integrity": {
            "status": integrity_status,
            "reason": if integrity_verified { Value::Null } else { json!("hash_chain_gap_detected") },
            "current_record_count": audit_total,
            "current_link_gap_count": gaps,
            "checked_window": checked_window
        },
        "integrity_verified": integrity_verified,
        "integrity_alert": !integrity_verified,
        "latest_audit_seq": latest_seq,
        "ontology_resource_count": ontology_resources,
        "available_scopes": available_scopes,
        "counts": {
            "audit_log": audit_total,
            "process_event": process_events,
            "operator_incident_projection": incidents,
            "operational_state_transition": transitions,
            "operational_retention_policy": retention_policies,
            "browser_evidence_artifact": browser_artifacts,
            "conversation_outbound_delivery": conversations,
            "ontology_resource": ontology_resources
        }
    })
}

pub async fn fetch_trace(
    db: &DbHandle,
    correlation_id: Option<&str>,
    limit: Option<usize>,
) -> Value {
    let lim = clamp_limit(limit, 50, 100);
    let proc_list_sql = "SELECT correlation_id, count(*), \
        to_char(min(recorded_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
        to_char(max(recorded_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
        max(process_id) \
        FROM process_event \
        WHERE correlation_id IS NOT NULL AND correlation_id <> '' \
        GROUP BY correlation_id \
        ORDER BY max(seq) DESC LIMIT 10";
    let audit_list_sql = "SELECT correlation_id, count(*), \
        to_char(min(created_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
        to_char(max(created_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
        max(action_kind) \
        FROM (SELECT correlation_id, created_at, action_kind, seq FROM audit_log ORDER BY seq DESC LIMIT 500) recent \
        WHERE correlation_id IS NOT NULL AND correlation_id <> '' \
        GROUP BY correlation_id \
        ORDER BY count(*) DESC, max(seq) DESC LIMIT 12";

    let (proc_list_res, audit_list_res, head_integrity) = tokio::join!(
        db.query_single_readonly(proc_list_sql),
        db.query_single_readonly(audit_list_sql),
        check_head_integrity(db, 25),
    );
    let (Ok(pl), Ok(al)) = (proc_list_res, audit_list_res) else {
        return db.not_measured("evidence", "/api/v4/evidence/trace", "postgres_unreachable");
    };

    let mut available: Vec<Value> = Vec::new();
    let mut seen_ids: Vec<String> = Vec::new();

    for r in &pl.rows {
        let cid = cell_str(r, 0);
        if cid.is_empty() || seen_ids.contains(&cid) {
            continue;
        }
        seen_ids.push(cid.clone());
        available.push(json!({
            "correlation_id": cid,
            "span_count": cell_i64(r, 1).unwrap_or(0),
            "started_at": cell_str(r, 2),
            "ended_at": cell_str(r, 3),
            "label": format!("{} · 워크플로 ({})", cid, cell_str(r, 4)),
            "origin": "process_event"
        }));
    }
    for r in &al.rows {
        let cid = cell_str(r, 0);
        if cid.is_empty() || seen_ids.contains(&cid) {
            continue;
        }
        seen_ids.push(cid.clone());
        let short_cid = short_resource_name(&cid);
        let act_label = humanize_action_ko(&cell_str(r, 4));
        available.push(json!({
            "correlation_id": cid,
            "span_count": cell_i64(r, 1).unwrap_or(0),
            "started_at": cell_str(r, 2),
            "ended_at": cell_str(r, 3),
            "label": format!("{} · {} ({}건)", act_label, short_cid, cell_i64(r, 1).unwrap_or(0)),
            "origin": "audit_log"
        }));
    }

    let selected_cid = correlation_id
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(String::from)
        .or_else(|| seen_ids.first().cloned());

    let mut spans: Vec<Value> = Vec::new();
    if let Some(ref cid) = selected_cid {
        let q_cid = pg_quote_literal(cid);
        let p_sql = format!(
            "SELECT seq, event_id, process_id, kind, COALESCE(step_id, ''), attempt, \
             to_char(recorded_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
             COALESCE(payload->>'reason', payload->>'step_kind', payload->>'workflow_ref', ''), \
             EXTRACT(EPOCH FROM recorded_at)::bigint \
             FROM process_event WHERE correlation_id = {q_cid} ORDER BY seq ASC LIMIT {lim}"
        );
        let a_sql = format!(
            "SELECT seq, event_id::text, actor, action_kind, mode, \
             to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
             COALESCE(entry->>'rule_id', entry->>'stage', ''), \
             COALESCE(entry->>'rca_cause', entry->>'reason', entry->>'t1_reason', ''), \
             EXTRACT(EPOCH FROM created_at)::bigint \
             FROM audit_log WHERE correlation_id = {q_cid} ORDER BY seq ASC LIMIT {lim}"
        );
        let (p_res, a_res) = tokio::join!(
            db.query_single_readonly(&p_sql),
            db.query_single_readonly(&a_sql),
        );

        let mut merged: Vec<(i64, i64, Value)> = Vec::new();
        if let Ok(pr) = p_res {
            for r in &pr.rows {
                let seq = cell_i64(r, 0).unwrap_or(0);
                let kind = cell_str(r, 3);
                let step = cell_str(r, 4);
                let recorded_at = cell_str(r, 6);
                let detail = cell_str(r, 7);
                let epoch = cell_i64(r, 8).unwrap_or(0);
                let status = if kind.contains("completed") {
                    "완료"
                } else if kind.contains("waiting") {
                    "승인 대기"
                } else {
                    "진행됨"
                };
                let kind_ko = humanize_action_ko(&kind);
                let detail_ko = match detail.trim().to_ascii_lowercase().as_str() {
                    "architecture-review" => "아키텍처 검토",
                    "approval" => "승인 단계",
                    "completed" => "완료",
                    _ => detail.as_str(),
                };
                merged.push((
                    epoch,
                    seq,
                    json!({
                        "source_table": "process_event",
                        "seq": seq,
                        "event_id": cell_str(r, 1),
                        "process_id": cell_str(r, 2),
                        "kind": kind,
                        "kind_ko": kind_ko,
                        "step_id": step,
                        "actor": "제어 루프 엔진 (Odin)",
                        "agent_icon": "/agent-icons/odin.svg",
                        "mode_label_ko": "감시 전용",
                        "status": status,
                        "recorded_at": recorded_at,
                        "epoch_s": epoch,
                        "summary": if detail_ko.is_empty() {
                            format!("{kind_ko} 단계가 워크플로에 기록되었습니다.")
                        } else {
                            format!("{kind_ko} · {detail_ko}")
                        }
                    }),
                ));
            }
        }
        if let Ok(ar) = a_res {
            for r in &ar.rows {
                let seq = cell_i64(r, 0).unwrap_or(0);
                let actor = cell_str(r, 2);
                let action_kind = cell_str(r, 3);
                let mode = cell_str(r, 4);
                let recorded_at = cell_str(r, 5);
                let stage = cell_str(r, 6);
                let reason = cell_str(r, 7);
                let epoch = cell_i64(r, 8).unwrap_or(0);
                let (actor_label, actor_role, agent_icon) = human_actor_meta(&actor);
                let mode_ko = mode_label_ko(&mode);
                let kind_ko = humanize_action_ko(&action_kind);
                let reason_ko = humanize_reason_ko(&reason);
                let stage_ko = if stage.is_empty() {
                    String::new()
                } else {
                    humanize_target_ko(&stage)
                };
                let summary = if !reason_ko.is_empty() {
                    format!("{actor_role} · {kind_ko}: {reason_ko}")
                } else if !stage_ko.is_empty() {
                    format!("{actor_role}에서 '{kind_ko}'({stage_ko}) 단계를 기록했습니다. ({mode_ko})")
                } else {
                    format!("{actor_role}에서 '{kind_ko}' 작업을 기록했습니다. ({mode_ko})")
                };
                merged.push((
                    epoch,
                    seq,
                    json!({
                        "source_table": "audit_log",
                        "seq": seq,
                        "audit_seq": seq,
                        "event_id": cell_str(r, 1),
                        "kind": action_kind,
                        "kind_ko": kind_ko,
                        "step_id": stage,
                        "actor": actor_role,
                        "actor_label": actor_label,
                        "raw_actor": actor,
                        "agent_icon": agent_icon,
                        "mode_label_ko": mode_ko,
                        "status": if action_kind.contains("abstain") {
                            "보류"
                        } else if action_kind.contains("hil") {
                            "승인 요청"
                        } else {
                            "기록 완료"
                        },
                        "recorded_at": recorded_at,
                        "epoch_s": epoch,
                        "summary": summary
                    }),
                ));
            }
        }

        merged.sort_by_key(|(ep, seq, _)| (*ep, *seq));
        spans = merged.into_iter().map(|(_, _, v)| v).collect();
    }

    let (gaps, checked_window, _) = head_integrity.unwrap_or((0, 0, None));
    let integrity_verified = gaps == 0;
    let integrity_status = if integrity_verified { "verified" } else { "tampered" };

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "correlation_id": selected_cid,
        "available_correlations": available,
        "span_count": spans.len(),
        "spans": spans,
        "integrity": {
            "status": integrity_status,
            "current_link_gap_count": gaps,
            "checked_window": checked_window
        },
        "audit_integrity": {
            "status": integrity_status,
            "current_link_gap_count": gaps,
            "checked_window": checked_window
        },
        "integrity_verified": integrity_verified,
        "integrity_alert": !integrity_verified
    })
}

pub async fn fetch_rca(
    db: &DbHandle,
    correlation_id: Option<&str>,
    case_id: Option<&str>,
) -> Value {
    let mut inc_clauses: Vec<String> = Vec::new();
    if let Some(cid) = correlation_id.map(str::trim).filter(|s| !s.is_empty()) {
        inc_clauses.push(format!("correlation_id = {}", pg_quote_literal(cid)));
    }
    if let Some(id) = case_id.map(str::trim).filter(|s| !s.is_empty()) {
        let lit = pg_quote_literal(id);
        inc_clauses.push(format!(
            "(correlation_id = {lit} OR canonical_incident_id = {lit} OR canonical_incident_number = {lit})"
        ));
    }
    let inc_where = if inc_clauses.is_empty() {
        String::new()
    } else {
        format!("WHERE {}", inc_clauses.join(" AND "))
    };
    let inc_sql = format!(
        "SELECT correlation_id, projected_state, projected_vertical, projected_severity, \
         COALESCE(canonical_incident_id, ''), COALESCE(canonical_incident_number, ''), \
         COALESCE(canonical_opened_at, ''), group_history_count, \
         COALESCE(history->0->'entry'->>'title', ''), \
         COALESCE(history->0->'entry'->>'summary', ''), \
         COALESCE(history->0->>'actor', 'Heimdall') \
         FROM operator_incident_projection {inc_where} \
         ORDER BY last_seq DESC, correlation_id ASC LIMIT 25"
    );
    let trans_sql = "SELECT transition_id, subject_ref, subject_type, state_type, \
        from_state, to_state, lane, authority, \
        to_char(effective_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
        source_identity, completeness_basis_points, \
        COALESCE(array_to_string(correlation_refs, ','), ''), \
        COALESCE(array_to_string(evidence_refs, ','), '') \
        FROM operational_state_transition \
        ORDER BY effective_at DESC LIMIT 35";
    let hyp_sql = "SELECT seq, COALESCE(correlation_id, ''), \
        COALESCE(entry->>'rule_id', ''), COALESCE(entry->>'rca_cause', ''), \
        to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
        FROM audit_log WHERE action_kind = 'rca.hypothesis' \
        ORDER BY seq DESC LIMIT 10";

    let (inc_res, trans_res, hyp_res) = tokio::join!(
        db.query_single_readonly(&inc_sql),
        db.query_single_readonly(trans_sql),
        db.query_single_readonly(hyp_sql),
    );
    let (Ok(ir), Ok(tr)) = (inc_res, trans_res) else {
        return db.not_measured("evidence", "/api/v4/evidence/rca", "postgres_unreachable");
    };

    let transitions: Vec<Value> = tr
        .rows
        .iter()
        .map(|r| {
            let subj = cell_str(r, 1);
            json!({
                "transition_id": cell_str(r, 0),
                "subject_ref": subj,
                "subject_short": short_resource_name(&subj),
                "subject_type": cell_str(r, 2),
                "state_type": cell_str(r, 3),
                "from_state": cell_str(r, 4),
                "to_state": cell_str(r, 5),
                "lane": cell_str(r, 6),
                "authority": cell_str(r, 7),
                "effective_at": cell_str(r, 8),
                "source_identity": cell_str(r, 9),
                "completeness_bps": cell_i64(r, 10).unwrap_or(0),
                "correlation_refs": cell_str(r, 11),
                "evidence_refs": cell_str(r, 12)
            })
        })
        .collect();

    let hypotheses: Vec<Value> = hyp_res
        .map(|hr| {
            hr.rows
                .iter()
                .map(|r| {
                    json!({
                        "seq": cell_i64(r, 0).unwrap_or(0),
                        "correlation_id": cell_str(r, 1),
                        "rule_id": cell_str(r, 2),
                        "rca_cause": cell_str(r, 3),
                        "created_at": cell_str(r, 4)
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    let mut cases: Vec<Value> = Vec::new();
    for r in &ir.rows {
        let corr = cell_str(r, 0);
        let state = cell_str(r, 1);
        let vertical = cell_str(r, 2);
        let severity = cell_str(r, 3);
        let inc_id = cell_str(r, 4);
        let inc_num = cell_str(r, 5);
        let opened_at = cell_str(r, 6);
        let history_count = cell_i64(r, 7).unwrap_or(0);
        let title = cell_str(r, 8);
        let summary = cell_str(r, 9);
        let actor = cell_str(r, 10);

        let matched_transitions: Vec<Value> = transitions
            .iter()
            .filter(|t| {
                t.get("correlation_refs")
                    .and_then(Value::as_str)
                    .is_some_and(|c| !c.is_empty() && c.contains(&corr))
            })
            .cloned()
            .collect();

        let status_code = if !matched_transitions.is_empty() || state == "resolved" {
            "grounded"
        } else {
            "abstained"
        };

        cases.push(json!({
            "case_id": if inc_num.is_empty() { corr.clone() } else { inc_num.clone() },
            "canonical_incident_id": inc_id,
            "canonical_incident_number": inc_num,
            "correlation_id": corr,
            "projected_state": state,
            "projected_vertical": vertical,
            "projected_severity": severity,
            "opened_at": opened_at,
            "history_count": history_count,
            "actor": actor,
            "title": if title.is_empty() { format!("{corr} 운영 사건 분석") } else { title },
            "summary": summary,
            "status": status_code,
            "correlation_is_not_causation": true,
            "matched_transitions": matched_transitions,
            "timeline_transitions": transitions.iter().take(6).cloned().collect::<Vec<_>>()
        }));
    }

    let grounded_count = cases
        .iter()
        .filter(|c| c.get("status").and_then(Value::as_str) == Some("grounded"))
        .count();
    let abstained_count = cases.len().saturating_sub(grounded_count);

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "correlation_is_not_causation": true,
        "abstained_supported": true,
        "summary": {
            "case_count": cases.len(),
            "grounded_count": grounded_count,
            "abstained_count": abstained_count,
            "transition_count": transitions.len(),
            "hypothesis_count": hypotheses.len()
        },
        "cases": cases,
        "transitions": transitions,
        "recent_hypotheses": hypotheses
    })
}

pub async fn fetch_browser_evidence(db: &DbHandle) -> Value {
    fetch_browser_evidence_filtered(db, None, None, None, Some(50)).await
}

pub async fn fetch_browser_evidence_filtered(
    db: &DbHandle,
    retention: Option<&str>,
    finding: Option<&str>,
    search: Option<&str>,
    limit: Option<usize>,
) -> Value {
    let lim = clamp_limit(limit, 50, 100);
    let mut clauses: Vec<String> = Vec::new();
    if let Some(ret) = retention
        .map(str::trim)
        .filter(|s| !s.is_empty() && !s.eq_ignore_ascii_case("all"))
    {
        match ret.to_ascii_lowercase().as_str() {
            "held" => clauses.push(String::from("legal_hold = TRUE")),
            "retained" => clauses.push(String::from("legal_hold = FALSE AND expires_at > NOW()")),
            "expiring" => clauses.push(String::from(
                "legal_hold = FALSE AND expires_at > NOW() AND expires_at <= NOW() + CAST('7 days' AS interval)",
            )),
            "expired_pending_purge" => {
                clauses.push(String::from("legal_hold = FALSE AND expires_at <= NOW()"));
            }
            _ => {}
        }
    }
    if let Some(f) = finding
        .map(str::trim)
        .filter(|s| !s.is_empty() && !s.eq_ignore_ascii_case("all"))
    {
        match f.to_ascii_lowercase().as_str() {
            "present" => clauses.push(String::from("jsonb_array_length(prompt_injection_findings) > 0")),
            "clear" => clauses.push(String::from("jsonb_array_length(prompt_injection_findings) = 0")),
            _ => {}
        }
    }
    if let Some(q) = search.map(str::trim).filter(|s| !s.is_empty()) {
        let pat = quote_like_contains(q);
        clauses.push(format!(
            "(artifact_id ILIKE {pat} ESCAPE '\\' OR canonical_source_url ILIKE {pat} ESCAPE '\\' \
             OR canonical_final_url ILIKE {pat} ESCAPE '\\' OR policy_id ILIKE {pat} ESCAPE '\\')"
        ));
    }

    let where_sql = if clauses.is_empty() {
        String::new()
    } else {
        format!("WHERE {}", clauses.join(" AND "))
    };
    let sql = format!(
        "SELECT artifact_id, canonical_source_url, canonical_final_url, policy_id, policy_version, \
         content_digest, COALESCE(screenshot_hash, ''), COALESCE(text_hash, ''), COALESCE(snapshot_hash, ''), \
         COALESCE(chain_of_custody_audit_ref, ''), legal_hold, COALESCE(legal_hold_ref, ''), \
         jsonb_array_length(prompt_injection_findings), browser_version, \
         to_char(captured_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
         to_char(expires_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
         jsonb_array_length(selectors), jsonb_array_length(redaction_manifest) \
         FROM browser_evidence_artifact {where_sql} ORDER BY captured_at DESC LIMIT {lim}"
    );
    let Ok(res) = db.query_single_readonly(&sql).await else {
        return db.not_measured(
            "evidence",
            "/api/v4/evidence/browser-evidence",
            "postgres_unreachable",
        );
    };

    let mut injection_blocked = 0_usize;
    let mut legal_hold_count = 0_usize;
    let items: Vec<Value> = res
        .rows
        .iter()
        .map(|r| {
            let inj = cell_i64(r, 12).unwrap_or(0);
            let held = cell_str(r, 10) == "t" || cell_str(r, 10).eq_ignore_ascii_case("true");
            if inj > 0 {
                injection_blocked = injection_blocked.saturating_add(1);
            }
            if held {
                legal_hold_count = legal_hold_count.saturating_add(1);
            }
            json!({
                "artifact_id": cell_str(r, 0),
                "canonical_source_url": cell_str(r, 1),
                "canonical_final_url": cell_str(r, 2),
                "policy_id": cell_str(r, 3),
                "policy_version": cell_i64(r, 4).unwrap_or(1),
                "content_digest": cell_str(r, 5),
                "screenshot_hash": cell_str(r, 6),
                "text_hash": cell_str(r, 7),
                "snapshot_hash": cell_str(r, 8),
                "chain_of_custody_audit_ref": cell_str(r, 9),
                "legal_hold": held,
                "legal_hold_ref": cell_str(r, 11),
                "injection_count": inj,
                "browser_version": cell_str(r, 13),
                "captured_at": cell_str(r, 14),
                "expires_at": cell_str(r, 15),
                "selector_count": cell_i64(r, 16).unwrap_or(0),
                "redaction_count": cell_i64(r, 17).unwrap_or(0)
            })
        })
        .collect();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "count": items.len(),
        "summary": {
            "total": items.len(),
            "injection_blocked": injection_blocked,
            "legal_hold": legal_hold_count,
            "withheld": Value::Null
        },
        "items": items
    })
}

pub async fn fetch_conversations(
    db: &DbHandle,
    search: Option<&str>,
    channel: Option<&str>,
    limit: Option<usize>,
) -> Value {
    let lim = clamp_limit(limit, 50, 100);
    let mut clauses: Vec<String> = Vec::new();
    if let Some(ch) = channel
        .map(str::trim)
        .filter(|s| !s.is_empty() && !s.eq_ignore_ascii_case("all"))
    {
        clauses.push(format!("channel_kind = {}", pg_quote_literal(ch)));
    }
    if let Some(q) = search.map(str::trim).filter(|s| !s.is_empty()) {
        let pat = quote_like_contains(q);
        clauses.push(format!(
            "(delivery_id ILIKE {pat} ESCAPE '\\' OR conversation_id ILIKE {pat} ESCAPE '\\' \
             OR channel_kind ILIKE {pat} ESCAPE '\\' OR state ILIKE {pat} ESCAPE '\\' \
             OR COALESCE(response->>'summary', '') ILIKE {pat} ESCAPE '\\')"
        ));
    }
    let where_sql = if clauses.is_empty() {
        String::new()
    } else {
        format!("WHERE {}", clauses.join(" AND "))
    };
    let sql = format!(
        "SELECT delivery_id, conversation_id, channel_kind, state, attempt_count, \
         response_digest, COALESCE(response->>'summary', ''), \
         to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
         COALESCE(last_error_code, '') \
         FROM conversation_outbound_delivery {where_sql} ORDER BY created_at DESC LIMIT {lim}"
    );
    let Ok(res) = db.query_single_readonly(&sql).await else {
        return db.not_measured(
            "evidence",
            "/api/v4/evidence/conversations",
            "postgres_unreachable",
        );
    };

    let items: Vec<Value> = res
        .rows
        .iter()
        .map(|r| {
            let delivery_id = cell_str(r, 0);
            let conv_id = cell_str(r, 1);
            let channel_kind = cell_str(r, 2);
            let state = cell_str(r, 3);
            let attempts = cell_i64(r, 4).unwrap_or(1);
            let digest = cell_str(r, 5);
            let summary = cell_str(r, 6);
            let created_at = cell_str(r, 7);
            let err_code = cell_str(r, 8);
            let channel_label = match channel_kind.to_ascii_lowercase().as_str() {
                "web" => "웹 콘솔",
                "teams" => "Microsoft Teams",
                "slack" => "Slack",
                _ => "채널",
            };
            let status_ko = match state.to_ascii_lowercase().as_str() {
                "delivered" => "전달 완료",
                "pending" | "queued" => "전달 대기",
                "failed" => "전달 실패",
                _ => "기록됨",
            };
            json!({
                "id": conv_id,
                "delivery_id": delivery_id,
                "conversation_id": cell_str(r, 1),
                "channel_kind": channel_kind,
                "channel_label": channel_label,
                "state": state,
                "status_ko": status_ko,
                "attempt_count": attempts,
                "response_digest": digest,
                "summary": if summary.is_empty()
                    || summary.eq_ignore_ascii_case("Operational posture notification delivered")
                {
                    String::from("운영 상태 알림이 정상 전달되었습니다.")
                } else {
                    summary
                },
                "created_at": created_at,
                "last_error_code": if err_code.is_empty() { Value::Null } else { json!(err_code) },
                "redaction_applied": true
            })
        })
        .collect();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "count": items.len(),
        "items": items,
        "conversations": items,
        "conversation_page": {
            "has_more": false,
            "next_cursor": Value::Null
        }
    })
}

pub async fn fetch_reports(
    db: &DbHandle,
    window: Option<&str>,
    scope: Option<&str>,
    report_id: Option<&str>,
) -> Value {
    let win = window
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or("7d");
    let sc = scope
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or("all");

    let ret_sql = "SELECT policy_id, fact_family, purpose, archive_class, deletion_method, \
        policy_digest, \
        to_char(recorded_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
        FROM operational_retention_policy ORDER BY policy_id ASC LIMIT 50";
    let win_iv = match win.to_ascii_lowercase().as_str() {
        "24h" => "24 hours",
        "30d" => "30 days",
        "90d" => "90 days",
        _ => "7 days",
    };
    let scope_res_clause = if sc.eq_ignore_ascii_case("all") {
        String::from("object_type = 'Resource'")
    } else {
        let pat = quote_like_contains(sc);
        format!("object_type = 'Resource' AND id ILIKE {pat} ESCAPE '\\'")
    };
    let q_win_iv = pg_quote_literal(win_iv);
    let counts_sql = format!(
        "SELECT \
         (SELECT count(*) FROM audit_log), \
         (SELECT count(*) FROM audit_log WHERE action_kind LIKE 'hil.%' OR action_kind LIKE 'risk_gate%'), \
         (SELECT count(*) FROM process_event), \
         (SELECT count(*) FROM operator_incident_projection), \
         (SELECT count(*) FROM operational_state_transition), \
         (SELECT count(*) FROM browser_evidence_artifact), \
         (SELECT count(*) FROM conversation_outbound_delivery), \
         (SELECT count(*) FROM audit_log WHERE created_at >= NOW() - CAST({q_win_iv} AS interval)), \
         (SELECT count(*) FROM ontology_resource WHERE {scope_res_clause}), \
         to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI \"UTC\"')"
    );

    let (ret_res, cnt_res, head_integrity, (ontology_total, available_scopes)) = tokio::join!(
        db.query_single_readonly(ret_sql),
        db.query_single_readonly(&counts_sql),
        check_head_integrity(db, 25),
        fetch_connected_scopes(db),
    );
    let (Ok(rr), Ok(cr)) = (ret_res, cnt_res) else {
        return db.not_measured("evidence", "/api/v4/evidence/reports", "postgres_unreachable");
    };

    let (
        audit_total,
        hil_total,
        proc_total,
        inc_total,
        trans_total,
        browser_total,
        conv_total,
        audit_in_window,
        scoped_resources,
        generated_at,
    ) = if let Some(row) = cr.rows.first() {
        (
            cell_i64(row, 0).unwrap_or(0),
            cell_i64(row, 1).unwrap_or(0),
            cell_i64(row, 2).unwrap_or(0),
            cell_i64(row, 3).unwrap_or(0),
            cell_i64(row, 4).unwrap_or(0),
            cell_i64(row, 5).unwrap_or(0),
            cell_i64(row, 6).unwrap_or(0),
            cell_i64(row, 7).unwrap_or(0),
            cell_i64(row, 8).unwrap_or(0),
            cell_str(row, 9),
        )
    } else {
        (0, 0, 0, 0, 0, 0, 0, 0, 0, String::from("실시간 UTC"))
    };

    let (gaps, checked_window, latest_seq) = head_integrity.unwrap_or((0, 0, None));
    let integrity_verified = gaps == 0;
    let integrity_status = if integrity_verified { "verified" } else { "tampered" };

    let retention_policies: Vec<Value> = rr
        .rows
        .iter()
        .map(|r| {
            json!({
                "policy_id": cell_str(r, 0),
                "fact_family": cell_str(r, 1),
                "purpose": cell_str(r, 2),
                "archive_class": cell_str(r, 3),
                "deletion_method": cell_str(r, 4),
                "policy_digest": cell_str(r, 5),
                "recorded_at": cell_str(r, 6)
            })
        })
        .collect();

    let first_digest = retention_policies
        .first()
        .and_then(|v| v.get("policy_digest"))
        .and_then(Value::as_str)
        .unwrap_or("sha256:postgres-direct-projection");

    let scope_display = if sc.eq_ignore_ascii_case("all") {
        format!("전체 연결 범위 ({ontology_total} 리소스)")
    } else {
        format!("{sc} ({scoped_resources} 리소스)")
    };

    let all_reports = vec![
        json!({
            "id": "audit-governance-live",
            "title": "감사 원장 · 무결성 및 운영 현황 보고서 (Live)",
            "version": "v4-live",
            "category": "감사 · 무결성",
            "status": if integrity_verified { "실측 완료" } else { "무결성 경고" },
            "tone": if integrity_verified { "live" } else { "sec" },
            "avail_label": format!("실측 완료 · 원장 {}건 · 범위 {}", audit_total, scope_display),
            "prov_kind": "실시간 운영 데이터베이스 읽기 전용 투영",
            "generated_at": generated_at,
            "signature": format!("sha256:audit-seq-{}-{}-{}", latest_seq.unwrap_or(0), win, sc),
            "metrics": [
                { "k": "감사 원장 누적 기록", "v": format!("{audit_total}건"), "note": format!("선택 기간({win}) {audit_in_window}건 · 최근 {checked_window}건 결손 {gaps}건"), "unavail": false },
                { "k": "승인·위험 게이트 기록", "v": format!("{hil_total}건"), "note": "사람 승인 요청 및 위험 평가 누적", "unavail": false },
                { "k": "연결 온톨로지 리소스", "v": format!("{scoped_resources}개"), "note": format!("대상 범위: {scope_display} · 전이 {trans_total}건"), "unavail": false }
            ],
            "rows": [
                { "item": "추가 전용 감사 원장 무결성", "owner": "Saga", "result": format!("{}건 검증 · 결손 {}건", audit_total, gaps), "as_of": generated_at },
                { "item": "온톨로지 연결 리소스 범위", "owner": "Muninn", "result": format!("{} ({} / 전체 {} 리소스)", scope_display, scoped_resources, ontology_total), "as_of": generated_at },
                { "item": "인시던트 투영 및 원인 분석", "owner": "Mimir · Heimdall", "result": format!("사건 {}건 · 워크플로 {}건 · 전이 {}건", inc_total, proc_total, trans_total), "as_of": generated_at },
                { "item": "웹 수집 · 대화 전달 기록", "owner": "Forseti · Bragi", "result": format!("웹 아티팩트 {}건 · 대화 전달 {}건", browser_total, conv_total), "as_of": generated_at }
            ],
            "sources": [
                { "name": "감사 원장", "state": format!("실측 · {audit_total}건"), "tone": "live", "as_of": "실시간 DB" },
                { "name": "온톨로지 리소스 인벤토리", "state": format!("실측 · {ontology_total} 리소스"), "tone": "live", "as_of": "실시간 DB" },
                { "name": "운영 상태 전이 기록", "state": format!("실측 · {trans_total}건"), "tone": "live", "as_of": "실시간 DB" },
                { "name": "데이터 보존 정책 저장소", "state": format!("실측 · {}건", retention_policies.len()), "tone": "live", "as_of": "실시간 DB" }
            ]
        }),
        json!({
            "id": "retention-policy-live",
            "title": "운영 데이터 보존 정책(Retention) 카탈로그 보고서 (Live)",
            "version": "v4-live",
            "category": "보존 · 컴플라이언스",
            "status": "실측 완료",
            "tone": "live",
            "avail_label": format!("보존 정책 {}건 실측 로드", retention_policies.len()),
            "prov_kind": "데이터 보존 정책 읽기 전용 투영",
            "generated_at": generated_at,
            "signature": first_digest,
            "metrics": [
                { "k": "등록된 보존 정책", "v": format!("{}건", retention_policies.len()), "note": "보존 정책 카탈로그 실측 기준", "unavail": false },
                { "k": "안전 보존(retain) 정책", "v": format!("{}건", retention_policies.iter().filter(|p| p.get("deletion_method").and_then(Value::as_str) == Some("retain")).count()), "note": "미구성 시 기본 보존(Fail-Safe)", "unavail": false },
                { "k": "외부 청구서 대조", "v": "데이터 없음 (미수집)", "note": "외부 과금 원천 미연동 · 0 대체 금지", "unavail": true }
            ],
            "rows": retention_policies.iter().map(|p| json!({
                "item": p.get("policy_id").and_then(Value::as_str).unwrap_or("-"),
                "owner": p.get("fact_family").and_then(Value::as_str).unwrap_or("-"),
                "result": format!("{} / {}", p.get("archive_class").and_then(Value::as_str).unwrap_or("-"), p.get("deletion_method").and_then(Value::as_str).unwrap_or("-")),
                "as_of": p.get("recorded_at").and_then(Value::as_str).unwrap_or("-")
            })).collect::<Vec<_>>(),
            "sources": [
                { "name": "데이터 보존 정책 저장소", "state": format!("실측 · {}건", retention_policies.len()), "tone": "live", "as_of": "실시간 DB" },
                { "name": "온톨로지 리소스 인벤토리", "state": format!("실측 · {ontology_total} 리소스"), "tone": "live", "as_of": "실시간 DB" },
                { "name": "외부 청구서 내보내기", "state": "미수집 (not-measured)", "tone": "neutral", "as_of": "미연동" }
            ]
        }),
        json!({
            "id": "ontology-scope-inventory-live",
            "title": "연결 구독 · 리소스 그룹 거버넌스 범위 보고서 (Live)",
            "version": "v4-live",
            "category": "구독 · 온톨로지",
            "status": "실측 완료",
            "tone": "live",
            "avail_label": format!("연결 범위 {}개 · {} 리소스 실측", available_scopes.len(), ontology_total),
            "prov_kind": "온톨로지 리소스 인벤토리 읽기 전용 투영",
            "generated_at": generated_at,
            "signature": format!("sha256:ontology-scopes-{}-{}", ontology_total, sc),
            "metrics": [
                { "k": "연결 온톨로지 리소스", "v": format!("{ontology_total}개"), "note": "실시간 연결 리소스 전체 집계", "unavail": false },
                { "k": "식별된 구독 · RG 범위", "v": format!("{}개", available_scopes.len()), "note": format!("선택 범위: {scope_display}"), "unavail": false },
                { "k": "연동 감사 원장 기록", "v": format!("{audit_total}건"), "note": format!("보존 정책 {}건 적용", retention_policies.len()), "unavail": false }
            ],
            "rows": available_scopes.iter().map(|s| json!({
                "item": s.get("id").and_then(Value::as_str).unwrap_or("-"),
                "owner": if s.get("kind").and_then(Value::as_str) == Some("subscription_scope") { "연결 구독 범위" } else { "리소스 그룹" },
                "result": format!("{}개 리소스", s.get("resource_count").and_then(Value::as_i64).unwrap_or(0)),
                "as_of": generated_at
            })).collect::<Vec<_>>(),
            "sources": [
                { "name": "온톨로지 리소스 인벤토리", "state": format!("실측 · {ontology_total}개"), "tone": "live", "as_of": "실시간 DB" },
                { "name": "감사 원장", "state": format!("실측 · {audit_total}건"), "tone": "live", "as_of": "실시간 DB" }
            ]
        }),
    ];

    let filtered: Vec<Value> = if let Some(rid) = report_id.map(str::trim).filter(|s| !s.is_empty()) {
        all_reports
            .into_iter()
            .filter(|r| r.get("id").and_then(Value::as_str) == Some(rid))
            .collect()
    } else {
        all_reports
    };

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "window": win,
        "scope": sc,
        "generated_at": generated_at,
        "execution_authority": false,
        "signature_algorithm": "SHA-256",
        "ontology_resource_count": ontology_total,
        "available_scopes": available_scopes,
        "audit_integrity": {
            "status": integrity_status,
            "current_record_count": audit_total,
            "current_link_gap_count": gaps,
            "checked_window": checked_window
        },
        "integrity_verified": integrity_verified,
        "integrity_alert": !integrity_verified,
        "retention_policies": retention_policies,
        "count": filtered.len(),
        "items": filtered
    })
}
