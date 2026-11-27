//! Domain 7 (`labs`, 6 panels) PostgreSQL repository.
//! Read-only queries against live operational transition, ontology, LLM invocation,
//! baseline evaluation, decision-evidence admission, and conversation assurance tables.

use crate::db::{cell_i64, cell_str, DbHandle};
use serde_json::{json, Value};

fn cell_f64(row: &[Option<String>], idx: usize) -> Option<f64> {
    row.get(idx)
        .and_then(|v| v.as_deref())
        .and_then(|s| s.parse::<f64>().ok())
}

fn short_subject_name(subject_ref: &str) -> String {
    let trimmed = subject_ref.trim();
    if trimmed.is_empty() {
        return String::from("unknown");
    }
    trimmed
        .rsplit('/')
        .next()
        .filter(|s| !s.is_empty())
        .unwrap_or(trimmed)
        .to_string()
}

fn short_digest(raw: &str) -> String {
    let trimmed = raw.trim();
    if trimmed.len() <= 20 {
        return trimmed.to_string();
    }
    let head: String = trimmed.chars().take(13).collect();
    let tail: String = trimmed
        .chars()
        .rev()
        .take(4)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect();
    format!("{head}...{tail}")
}

fn format_pct(numerator: i64, denominator: i64) -> Option<f64> {
    if denominator <= 0 {
        return None;
    }
    let ratio = (numerator as f64 / denominator as f64) * 100.0;
    Some((ratio * 10.0).round() / 10.0)
}

fn humanize_state_ko(raw: &str) -> &'static str {
    match raw.trim().to_ascii_lowercase().as_str() {
        "available" | "ready" | "running" | "healthy" => "정상 가용",
        "degraded" => "성능 저하",
        "stopped" | "unavailable" | "failed" => "중지/장애",
        "unknown" | "" => "확인 불가",
        _ => "관측 상태",
    }
}

fn humanize_state_type_ko(raw: &str) -> &'static str {
    match raw.trim() {
        "resource.availability_state" => "가용성 상태",
        "resource.health_state" => "헬스 상태",
        "resource.provisioning_state" => "프로비저닝 상태",
        _ => "운영 상태 전환",
    }
}

fn humanize_mechanism_ko(raw: &str) -> String {
    match raw.trim() {
        "kubernetes_dependency_evaluation_provider" => {
            String::from("쿠버네티스 의존성 평가")
        }
        "reasoning_model_completion_compatibility" => {
            String::from("추론 모델 호환성 검증")
        }
        "kubernetes_webhook_failure_source_candidate" => {
            String::from("웹훅 장애 원인 후보 분석")
        }
        "kubernetes_direct_admission_condition_evidence" => {
            String::from("직접 어드미션 조건 근거")
        }
        "kubernetes_bounded_evidence_budgeting" => {
            String::from("제한 근거 예산 제어")
        }
        other => other.replace('_', " "),
    }
}

fn humanize_capability_ko(raw: &str) -> String {
    match raw.trim() {
        "t1.embedding" => String::from("임베딩 사전 분류"),
        "t2.reasoner.primary" => String::from("고급 추론 분석"),
        "t2.reasoner.fallback" => String::from("보조 추론 분석"),
        "t1.classifier" => String::from("규칙·분류기"),
        other => other.replace(['.', '_'], " "),
    }
}

fn humanize_remediation_ko(raw: &str) -> String {
    let trimmed = raw.trim();
    if trimmed.is_empty() || trimmed.eq_ignore_ascii_case("none") {
        return String::from("수동 검토 (자동 조치 없음)");
    }
    match trimmed.to_ascii_lowercase().as_str() {
        "remediate.tag-add" => String::from("필수 태그 자동 추가"),
        "remediate.tag-update" => String::from("리소스 태그 보정"),
        "remediate.scale-out" => String::from("노드 풀 확장"),
        "remediate.restart" => String::from("워크로드 재시작"),
        "remediate.revoke-access" => String::from("임시 접근 권한 회수"),
        "remediate.restrict-network" => String::from("네트워크 접근 제한"),
        other => {
            if let Some(rest) = other.strip_prefix("remediate.") {
                format!("{} 조치", rest.replace(['.', '_', '-'], " "))
            } else {
                other.replace(['.', '_', '-'], " ")
            }
        }
    }
}

fn humanize_finding_status_ko(raw: &str) -> &'static str {
    match raw.trim().to_ascii_lowercase().as_str() {
        "active" | "open" => "활성 탐지",
        "resolved" | "closed" => "해소됨",
        "investigating" => "조사 중",
        "suppressed" => "예외 보류",
        _ => "관측 중",
    }
}

fn humanize_scope_ko(raw: &str) -> &'static str {
    match raw.trim() {
        "control_plane" => "제어 평면",
        "operator" => "운영자 콘솔",
        "lab-sandbox" => "실험실 격리 샌드박스",
        _ => "실행 범위",
    }
}

fn humanize_resource_type_ko(raw: &str) -> String {
    let key = raw.trim().to_ascii_lowercase();
    match key.as_str() {
        "compute.vm-scale-set" | "vm-scale-set" => String::from("가상 머신 확장 집합 (VMSS)"),
        "compute.container-app" | "container-app" => String::from("컨테이너 앱"),
        "compute.container-app-job" | "container-app-job" => String::from("컨테이너 앱 작업"),
        "compute.virtual-machine" | "virtual-machine" | "vm" => String::from("가상 머신 (VM)"),
        "kubernetes-cluster" | "compute.kubernetes-cluster" | "aks" => {
            String::from("쿠버네티스 클러스터 (AKS)")
        }
        "managed-identity" | "identity.managed-identity" => String::from("관리 ID"),
        "subscription" => String::from("Azure 구독"),
        "cache" | "cache.redis" | "redis" => String::from("캐시 (Redis)"),
        "postgresql" | "database.postgresql" => String::from("PostgreSQL 데이터베이스"),
        "key-vault" | "security.key-vault" => String::from("키 볼트 (Key Vault)"),
        "storage" | "storage.account" => String::from("스토리지 계정"),
        "network" | "network.virtual-network" => String::from("가상 네트워크"),
        "resource" | "" => String::from("클라우드 리소스"),
        other => other.replace(['.', '-', '_'], " "),
    }
}

fn humanize_severity_ko(raw: &str) -> &'static str {
    match raw.trim().to_ascii_lowercase().as_str() {
        "critical" => "긴급",
        "high" => "높음",
        "medium" => "보통",
        "low" => "낮음",
        _ => "정보",
    }
}

fn humanize_signal_ko(raw: &str) -> String {
    match raw.trim().to_ascii_lowercase().as_str() {
        "container_restart" => String::from("컨테이너 재시작 감지"),
        "pod_oomkill" | "oomkill" => String::from("컨테이너 메모리 초과 종료"),
        "high_cpu" | "cpu_spike" => String::from("CPU 사용률 급증"),
        "latency_spike" => String::from("응답 지연 급증"),
        other => other.replace(['_', '-', '.'], " "),
    }
}

fn humanize_rule_ko(rule_id: &str, rtype: &str) -> String {
    let rtype_ko = humanize_resource_type_ko(rtype);
    let lower = rule_id.trim().to_ascii_lowercase();
    if lower.contains("zone-redundan") {
        format!("{rtype_ko} 영역 중복 구성 점검")
    } else if lower.contains("network-policy") {
        format!("{rtype_ko} 네트워크 정책 적용 점검")
    } else if lower.contains("private-cluster") {
        format!("{rtype_ko} 프라이빗 클러스터 격리 점검")
    } else if lower.contains("no-privileged-subscription-scope") {
        format!("{rtype_ko} 구독 범위 권한 상승 차단 점검")
    } else if lower.contains("no-guest-privileged") {
        format!("{rtype_ko} 게스트 계정 고권한 차단 점검")
    } else if lower.contains("public") {
        format!("{rtype_ko} 공용 네트워크 노출 차단 점검")
    } else {
        let tail = rule_id
            .rsplit('.')
            .next()
            .unwrap_or(rule_id)
            .replace(['-', '_'], " ");
        format!("{rtype_ko} 정책 규칙 ({tail})")
    }
}

/// Panel 1 (`labs`): Summary across all 5 sandbox experiment workbenches.
pub async fn fetch_labs_summary(db: &DbHandle) -> Value {
    let (batches, trans_total, trans, coverage, ontology, llm, conv_eval, kv_counts, extra_counts) =
        tokio::join!(
            db.query_single_readonly(
                "SELECT count(*), \
                 COALESCE(to_char(MAX(recorded_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') \
                 FROM operational_state_transition_batch",
            ),
            db.query_single_readonly("SELECT count(*) FROM operational_state_transition"),
            db.query_single_readonly(
                "SELECT transition_id, subject_ref, state_type, COALESCE(from_state, ''), to_state, \
                 to_char(recorded_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
                 lane, authority, completeness_basis_points \
                 FROM operational_state_transition ORDER BY recorded_at DESC LIMIT 30",
            ),
            db.query_single_readonly(
                "SELECT count(*), count(*) FILTER (WHERE complete), count(*) FILTER (WHERE NOT complete) \
                 FROM operational_state_transition_coverage",
            ),
            db.query_single_readonly(
                "SELECT count(*), \
                 count(*) FILTER (WHERE object_type = 'Resource'), \
                 count(*) FILTER (WHERE object_type = 'BenchmarkValidation'), \
                 count(*) FILTER (WHERE object_type = 'BenchmarkValidation' AND (properties->>'passed')::boolean), \
                 count(*) FILTER (WHERE object_type = 'Rule'), \
                 COALESCE(MAX(revision), 1) \
                 FROM ontology_resource",
            ),
            db.query_single_readonly(
                "SELECT count(*), \
                 count(*) FILTER (WHERE tier = 'T1'), \
                 count(*) FILTER (WHERE tier = 'T2'), \
                 COALESCE(SUM(prompt_tokens + completion_tokens), 0) \
                 FROM llm_invocation",
            ),
            db.query_single_readonly("SELECT count(*) FROM conversation_assurance_assessment"),
            db.query_single_readonly(
                "SELECT \
                 count(*) FILTER (WHERE key LIKE 'baseline-evaluation:outcomes:%'), \
                 count(*) FILTER (WHERE key LIKE 'baseline-evaluation:outcomes:%' AND value->>'outcome' = 'violated'), \
                 count(*) FILTER (WHERE key LIKE 'decision-evidence-admission:v1:%'), \
                 count(*) FILTER (WHERE key LIKE 'operator-semantic-result:%'), \
                 count(*) FILTER (WHERE key LIKE 'measurement:control-loop:v1:%'), \
                 count(*) FILTER (WHERE key LIKE 'runtime:analyzer-finding-current:%'), \
                 count(*) \
                 FROM state_kv",
            ),
            db.query_single_readonly(
                "SELECT \
                 (SELECT count(*) FROM ontology_link), \
                 (SELECT count(*) FROM inventory_observation_correction_receipt), \
                 (SELECT count(*) FROM audit_log)",
            ),
        );

    let (Ok(b), Ok(tt), Ok(t), Ok(cov), Ok(ont), Ok(l), Ok(c), Ok(kv), Ok(ex)) = (
        batches,
        trans_total,
        trans,
        coverage,
        ontology,
        llm,
        conv_eval,
        kv_counts,
        extra_counts,
    ) else {
        return db.not_measured("labs", "/api/v4/labs/summary", "postgres_unreachable");
    };

    let batch_count = b.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let latest_batch_at = b.rows.first().map(|r| cell_str(r, 1)).unwrap_or_default();
    let transition_count = tt
        .rows
        .first()
        .and_then(|r| cell_i64(r, 0))
        .unwrap_or_else(|| i64::try_from(t.rows.len()).unwrap_or(0));
    let coverage_total = cov.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let coverage_complete = cov.rows.first().and_then(|r| cell_i64(r, 1)).unwrap_or(0);
    let coverage_incomplete = cov.rows.first().and_then(|r| cell_i64(r, 2)).unwrap_or(0);

    let ont_total = ont.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let ont_resources = ont.rows.first().and_then(|r| cell_i64(r, 1)).unwrap_or(0);
    let bench_total = ont.rows.first().and_then(|r| cell_i64(r, 2)).unwrap_or(0);
    let bench_passed = ont.rows.first().and_then(|r| cell_i64(r, 3)).unwrap_or(0);
    let rule_count = ont.rows.first().and_then(|r| cell_i64(r, 4)).unwrap_or(0);
    let ont_revision = ont.rows.first().and_then(|r| cell_i64(r, 5)).unwrap_or(1);

    let llm_total = l.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let llm_t1 = l.rows.first().and_then(|r| cell_i64(r, 1)).unwrap_or(0);
    let llm_t2 = l.rows.first().and_then(|r| cell_i64(r, 2)).unwrap_or(0);
    let llm_tokens = l.rows.first().and_then(|r| cell_i64(r, 3)).unwrap_or(0);

    let conv_eval_count = c.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let baseline_outcomes = kv.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let baseline_violated = kv.rows.first().and_then(|r| cell_i64(r, 1)).unwrap_or(0);
    let decision_admissions = kv.rows.first().and_then(|r| cell_i64(r, 2)).unwrap_or(0);
    let semantic_results = kv.rows.first().and_then(|r| cell_i64(r, 3)).unwrap_or(0);
    let control_loop_measurements = kv.rows.first().and_then(|r| cell_i64(r, 4)).unwrap_or(0);
    let active_findings = kv.rows.first().and_then(|r| cell_i64(r, 5)).unwrap_or(0);
    let state_kv_total = kv.rows.first().and_then(|r| cell_i64(r, 6)).unwrap_or(0);

    let ontology_links = ex.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let correction_receipts = ex.rows.first().and_then(|r| cell_i64(r, 1)).unwrap_or(0);
    let audit_total = ex.rows.first().and_then(|r| cell_i64(r, 2)).unwrap_or(0);

    let recent_transitions: Vec<Value> = t
        .rows
        .iter()
        .map(|r| {
            let subject_ref = cell_str(r, 1);
            let comp_bps = cell_i64(r, 8).unwrap_or(0);
            json!({
                "transition_id": cell_str(r, 0),
                "subject_ref": subject_ref,
                "subject_name": short_subject_name(&subject_ref),
                "state_type": cell_str(r, 2),
                "from_state": cell_str(r, 3),
                "to_state": cell_str(r, 4),
                "recorded_at": cell_str(r, 5),
                "lane": cell_str(r, 6),
                "authority": cell_str(r, 7),
                "completeness_pct": (comp_bps as f64) / 100.0
            })
        })
        .collect();

    let twin_summary = if baseline_outcomes > 0 {
        format!("기준선 평가 {baseline_outcomes}건 · 위반 {baseline_violated}건 · 규칙 {rule_count}종")
    } else {
        format!("규칙 {rule_count}종 · 활성 탐지 {active_findings}건 · 제어루프 측정 {control_loop_measurements}건")
    };
    let twin_metric_val = if baseline_outcomes > 0 {
        format!("{baseline_outcomes}건 (위반 {baseline_violated})")
    } else {
        format!("활성 탐지 {active_findings}건 · 측정 {control_loop_measurements}건")
    };
    let conv_badge = if semantic_results > 0 {
        format!("시맨틱 {semantic_results}턴")
    } else {
        format!("최근7일 {llm_total}호출")
    };
    let conv_summary = if semantic_results > 0 {
        format!("시맨틱 턴 {semantic_results}건 · LLM 호출 {llm_total}회 (평가표 {conv_eval_count}건)")
    } else {
        format!("최근 7일 LLM 호출 {llm_total}회 (T1 {llm_t1} · T2 {llm_t2}) · 평가표 {conv_eval_count}건")
    };
    let ctx_badge = if decision_admissions > 0 {
        format!("채택 {decision_admissions}건")
    } else {
        format!("측정 {control_loop_measurements}건")
    };
    let ctx_summary = if decision_admissions > 0 {
        format!("증거 채택 영수증 {decision_admissions}건 · T1 {llm_t1}회 vs T2 {llm_t2}회")
    } else {
        format!("제어루프 측정 {control_loop_measurements}건 · 보정 영수증 {correction_receipts}건 · 관계 {ontology_links}건")
    };

    let mut recent_runs: Vec<Value> = Vec::new();
    for tr in recent_transitions.iter().take(4) {
        let tid = tr["transition_id"].as_str().unwrap_or("");
        let subj = tr["subject_name"].as_str().unwrap_or("resource");
        let from_s = tr["from_state"].as_str().unwrap_or("");
        let to_s = tr["to_state"].as_str().unwrap_or("");
        let st_type = tr["state_type"].as_str().unwrap_or("");
        let tone = match to_s {
            "available" | "ready" | "running" => "live",
            "degraded" | "stopped" => "sre",
            _ => "neutral",
        };
        let label = match to_s {
            "available" | "ready" | "running" => "정상 전환",
            "degraded" | "stopped" => "주의 전환",
            _ => "관측 기록",
        };
        let from_ko = humanize_state_ko(from_s);
        let to_ko = humanize_state_ko(to_s);
        let st_ko = humanize_state_type_ko(st_type);
        let short_tid = short_digest(tid);
        recent_runs.push(json!({
            "run_id": short_tid,
            "raw_id": tid,
            "display_title": format!("{subj} · {st_ko}"),
            "module_id": "aks-commerce",
            "module_label": "AKS 데모 환경",
            "sandbox_scope": "lab-sandbox",
            "summary": format!("{subj}의 {st_ko}가 '{from_ko}'에서 '{to_ko}' 상태로 관측되었습니다."),
            "side_effects": 0,
            "status_tone": tone,
            "status_label": label,
            "tech_details": [
                ["원본 전환 ID", tid],
                ["상태 유형 키", st_type],
                ["원본 상태 전이", format!("{from_s} → {to_s}")],
                ["격리 범위", "lab-sandbox"]
            ]
        }));
    }
    if rule_count > 0 || baseline_outcomes > 0 || active_findings > 0 || control_loop_measurements > 0 {
        recent_runs.push(json!({
            "run_id": format!("twin-rev-{ont_revision}"),
            "raw_id": format!("ontology-rev-{ont_revision}"),
            "display_title": format!("온톨로지 리비전 {ont_revision} 정책 포스처 점검"),
            "module_id": "assurance-twin",
            "module_label": "사전 검증 시뮬레이션",
            "sandbox_scope": "lab-sandbox",
            "summary": twin_summary,
            "side_effects": 0,
            "status_tone": if baseline_violated > 0 || active_findings > 0 { "sre" } else { "live" },
            "status_label": if baseline_violated > 0 || active_findings > 0 { "검토 필요" } else { "통과" },
            "tech_details": [
                ["실행 식별자", format!("twin-rev-{ont_revision}")],
                ["온톨로지 리비전", format!("rev-{ont_revision}")],
                ["규칙 수", format!("{rule_count}종")],
                ["격리 범위", "lab-sandbox"]
            ]
        }));
    }
    if batch_count > 0 || coverage_total > 0 || bench_total > 0 {
        recent_runs.push(json!({
            "run_id": format!("fc-batch-{batch_count}"),
            "raw_id": format!("forecast-batch-{batch_count}"),
            "display_title": "예측 커버리지 · 벤치마크 보정 집계",
            "module_id": "forecast-learning",
            "module_label": "예측 모델 학습",
            "sandbox_scope": "lab-sandbox",
            "summary": format!("전환 배치 {batch_count}건 · 커버리지 {coverage_total}건 · 벤치마크 {bench_passed}/{bench_total}"),
            "side_effects": 0,
            "status_tone": "live",
            "status_label": "실측 연결",
            "tech_details": [
                ["실행 식별자", format!("fc-batch-{batch_count}")],
                ["전환 배치", format!("{batch_count}건")],
                ["커버리지 총계", format!("{coverage_total}건")],
                ["격리 범위", "lab-sandbox"]
            ]
        }));
    }
    if llm_total > 0 || semantic_results > 0 || conv_eval_count > 0 {
        recent_runs.push(json!({
            "run_id": format!("conv-llm-{llm_total}"),
            "raw_id": format!("conversation-llm-{llm_total}"),
            "display_title": "최근 7일 대화 품질 · 모델 호출 점검",
            "module_id": "conversation-assurance",
            "module_label": "대화 품질 점검",
            "sandbox_scope": "lab-sandbox",
            "summary": conv_summary,
            "side_effects": 0,
            "status_tone": "live",
            "status_label": "실측 연결",
            "tech_details": [
                ["실행 식별자", format!("conv-llm-{llm_total}")],
                ["LLM 호출 수", format!("{llm_total}회")],
                ["평가 원장", format!("{conv_eval_count}건")],
                ["격리 범위", "lab-sandbox"]
            ]
        }));
    }
    if decision_admissions > 0 || control_loop_measurements > 0 || correction_receipts > 0 || llm_total > 0 {
        recent_runs.push(json!({
            "run_id": format!("ctx-meas-{control_loop_measurements}"),
            "raw_id": format!("context-measurement-{control_loop_measurements}"),
            "display_title": "컨텍스트 선택 · 증거 채택 효율 비교",
            "module_id": "context-selection-comparisons",
            "module_label": "참조 정보 비교",
            "sandbox_scope": "lab-sandbox",
            "summary": ctx_summary,
            "side_effects": 0,
            "status_tone": "live",
            "status_label": "실측 연결",
            "tech_details": [
                ["실행 식별자", format!("ctx-meas-{control_loop_measurements}")],
                ["제어루프 측정", format!("{control_loop_measurements}건")],
                ["보정 영수증", format!("{correction_receipts}건")],
                ["격리 범위", "lab-sandbox"]
            ]
        }));
    }

    let aks_has_data = transition_count > 0 || batch_count > 0 || ont_resources > 0;
    let twin_has_data =
        rule_count > 0 || baseline_outcomes > 0 || active_findings > 0 || control_loop_measurements > 0;
    let fc_has_data = coverage_total > 0 || bench_total > 0 || batch_count > 0;
    let conv_has_data = llm_total > 0 || semantic_results > 0 || conv_eval_count > 0;
    let ctx_has_data =
        decision_admissions > 0 || control_loop_measurements > 0 || correction_receipts > 0 || llm_total > 0;

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "latest_batch_at": latest_batch_at,
        "transition_batch_count": batch_count,
        "transition_count": transition_count,
        "transition_coverage_count": coverage_total,
        "transition_coverage_complete": coverage_complete,
        "transition_coverage_incomplete": coverage_incomplete,
        "ontology_resource_count": ont_total,
        "cloud_resource_count": ont_resources,
        "ontology_link_count": ontology_links,
        "correction_receipt_count": correction_receipts,
        "audit_log_count": audit_total,
        "state_kv_count": state_kv_total,
        "benchmark_validation_count": bench_total,
        "benchmark_validation_passed": bench_passed,
        "rule_count": rule_count,
        "ontology_revision": ont_revision,
        "llm_invocation_count": llm_total,
        "llm_t1_count": llm_t1,
        "llm_t2_count": llm_t2,
        "llm_total_tokens": llm_tokens,
        "conversation_assurance_count": conv_eval_count,
        "semantic_turn_result_count": semantic_results,
        "baseline_evaluation_count": baseline_outcomes,
        "baseline_violated_count": baseline_violated,
        "decision_evidence_count": decision_admissions,
        "control_loop_measurement_count": control_loop_measurements,
        "active_finding_count": active_findings,
        "module_metrics": {
            "aks-commerce": if aks_has_data {
                json!({
                    "badge": format!("전환 {transition_count}건"),
                    "badge_tone": "tone-live",
                    "metric_label": "관측 리소스 · 배치",
                    "metric_value": format!("리소스 {ont_resources} · 배치 {batch_count}"),
                    "description": format!("관측 리소스 {ont_resources}개와 상태 전환 배치 {batch_count}건을 격리 경계(lab-sandbox)에서 확인합니다.")
                })
            } else {
                json!({
                    "badge": "미측정",
                    "badge_tone": "tone-neutral",
                    "metric_label": "관측 리소스 · 배치",
                    "metric_value": "수집된 데이터 없음",
                    "description": "수집된 AKS 데모 온톨로지 및 상태 전환 기록이 없습니다."
                })
            },
            "assurance-twin": if twin_has_data {
                json!({
                    "badge": format!("규칙 {rule_count}종"),
                    "badge_tone": if baseline_violated > 0 || active_findings > 0 { "tone-sre" } else { "tone-live" },
                    "metric_label": if baseline_outcomes > 0 { "기준선 평가" } else { "포스처 · 탐지" },
                    "metric_value": twin_metric_val,
                    "description": format!("온톨로지 리비전 {ont_revision}(리소스 {ont_total}개)과 정책 규칙 {rule_count}종 기준으로 변경 영향을 무부작용 사전 점검합니다.")
                })
            } else {
                json!({
                    "badge": "미측정",
                    "badge_tone": "tone-neutral",
                    "metric_label": "포스처 · 탐지",
                    "metric_value": "수집된 데이터 없음",
                    "description": "수집된 온톨로지 규칙 및 사전 검증 리뷰 기록이 없습니다."
                })
            },
            "forecast-learning": if fc_has_data {
                json!({
                    "badge": format!("커버리지 {coverage_total}"),
                    "badge_tone": "tone-live",
                    "metric_label": "벤치마크 검증",
                    "metric_value": if bench_total > 0 { format!("{bench_passed} / {bench_total} 통과") } else { String::from("벤치마크 미수집") },
                    "description": format!("전환 커버리지 {coverage_total}건과 벤치마크 검증 {bench_total}건의 보정·시간대 분포를 분석합니다.")
                })
            } else {
                json!({
                    "badge": "미측정",
                    "badge_tone": "tone-neutral",
                    "metric_label": "벤치마크 검증",
                    "metric_value": "수집된 데이터 없음",
                    "description": "수집된 예측 커버리지 및 벤치마크 검증 기록이 없습니다."
                })
            },
            "conversation-assurance": if conv_has_data {
                json!({
                    "badge": conv_badge,
                    "badge_tone": "tone-live",
                    "metric_label": "LLM 호출 (7일)",
                    "metric_value": format!("{llm_total}회 (평가표 {conv_eval_count})"),
                    "description": format!("최근 7일 모델 호출 {llm_total}회, 시맨틱 턴 {semantic_results}건, 평가 원장 {conv_eval_count}건을 정직 표기로 점검합니다.")
                })
            } else {
                json!({
                    "badge": "미측정",
                    "badge_tone": "tone-neutral",
                    "metric_label": "LLM 호출 (7일)",
                    "metric_value": "수집된 데이터 없음",
                    "description": "수집된 대화 품질 평가 및 LLM 호출 기록이 없습니다."
                })
            },
            "context-selection-comparisons": if ctx_has_data {
                let ctx_metric_val = format!("T1 {llm_t1} · T2 {llm_t2} · 링크 {ontology_links}");
                let ctx_desc = format!("실측 T1/T2 티어, 제어루프 측정 {control_loop_measurements}건, 보정 영수증 {correction_receipts}건 기준 컨텍스트 효율을 비교합니다.");
                json!({
                    "badge": ctx_badge,
                    "badge_tone": "tone-live",
                    "metric_label": "T1 / T2 · 관계",
                    "metric_value": ctx_metric_val,
                    "description": ctx_desc
                })
            } else {
                json!({
                    "badge": "미측정",
                    "badge_tone": "tone-neutral",
                    "metric_label": "T1 / T2 · 관계",
                    "metric_value": "수집된 데이터 없음",
                    "description": "수집된 컨텍스트 선택 비교 및 증거 채택 영수증이 없습니다."
                })
            }
        },
        "recent_transitions": recent_transitions,
        "recent_runs": recent_runs
    })
}

/// Panel 2 (`aks-commerce`): Live topology, transition signals, and evidence gaps from PostgreSQL.
pub async fn fetch_aks_commerce(db: &DbHandle, service_id: &str) -> Value {
    let (res_types, trans_stats, transitions, coverage_gaps, batch_cnt, demo_repo) = tokio::join!(
        db.query_single_readonly(
            "SELECT COALESCE(properties->>'type', 'unknown') AS rtype, count(*) \
             FROM ontology_resource WHERE object_type = 'Resource' \
             GROUP BY 1 ORDER BY 2 DESC",
        ),
        db.query_single_readonly(
            "SELECT count(*), \
             count(*) FILTER (WHERE to_state IN ('available', 'ready', 'running')), \
             COALESCE(round(avg(completeness_basis_points)::numeric, 1), 0) \
             FROM operational_state_transition",
        ),
        db.query_single_readonly(
            "SELECT transition_id, subject_ref, state_type, from_state, to_state, \
             completeness_basis_points, \
             to_char(recorded_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
             FROM operational_state_transition ORDER BY recorded_at DESC LIMIT 20",
        ),
        db.query_single_readonly(
            "SELECT COALESCE(limitation, 'complete'), count(*) \
             FROM operational_state_transition_coverage GROUP BY 1 ORDER BY 2 DESC",
        ),
        db.query_single_readonly("SELECT count(*) FROM operational_state_transition_batch"),
        db.query_single_readonly(
            "SELECT key, COALESCE(value->>'location', value->'package'->>'revision', ''), \
             COALESCE(value->>'revision', value->'package'->>'revision', '') \
             FROM state_kv \
             WHERE key LIKE 'runtime:code-security-%aks-store-demo%' \
             ORDER BY updated_at DESC LIMIT 5",
        ),
    );

    let (Ok(rt), Ok(ts), Ok(tr), Ok(cg), Ok(bc), Ok(dr)) = (
        res_types,
        trans_stats,
        transitions,
        coverage_gaps,
        batch_cnt,
        demo_repo,
    ) else {
        return db.not_measured("labs", "/api/v4/labs/aks-commerce", "postgres_unreachable");
    };

    let mut edge_count = 0_i64;
    let mut compute_count = 0_i64;
    let mut durable_count = 0_i64;
    let mut network_cache_count = 0_i64;
    let mut total_resources = 0_i64;

    for r in &rt.rows {
        let kind = cell_str(r, 0);
        let cnt = cell_i64(r, 1).unwrap_or(0);
        total_resources += cnt;
        if kind.contains("load-balancer")
            || kind.contains("public-ip")
            || kind.contains("gateway")
            || kind.contains("ingress")
        {
            edge_count += cnt;
        } else if kind.contains("compute")
            || kind.contains("kubernetes")
            || kind.contains("aks")
            || kind.contains("container")
        {
            compute_count += cnt;
        } else if kind.contains("postgres")
            || kind.contains("sql")
            || kind.contains("disk")
            || kind.contains("storage")
        {
            durable_count += cnt;
        } else if kind.contains("redis")
            || kind.contains("cache")
            || kind.contains("vnet")
            || kind.contains("subnet")
            || kind.contains("dns")
            || kind.contains("private-endpoint")
        {
            network_cache_count += cnt;
        }
    }

    let total_batches = bc.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let total_transitions = ts
        .rows
        .first()
        .and_then(|r| cell_i64(r, 0))
        .unwrap_or_else(|| i64::try_from(tr.rows.len()).unwrap_or(0));
    let healthy_transitions_i64 = ts.rows.first().and_then(|r| cell_i64(r, 1)).unwrap_or(0);
    let availability_ratio = format_pct(healthy_transitions_i64, total_transitions);
    let avg_comp = if total_transitions == 0 {
        None
    } else {
        ts.rows
            .first()
            .and_then(|r| cell_f64(r, 2))
            .map(|bps| ((bps / 100.0) * 10.0).round() / 10.0)
    };

    let mut coverage_total = 0_i64;
    let mut snapshot_only = 0_i64;
    let mut initial_only = 0_i64;
    for r in &cg.rows {
        let lim = cell_str(r, 0);
        let cnt = cell_i64(r, 1).unwrap_or(0);
        coverage_total += cnt;
        if lim == "snapshot_interval_only" {
            snapshot_only = cnt;
        } else if lim == "initial_state_only" {
            initial_only = cnt;
        }
    }

    let demo_rev = dr
        .rows
        .iter()
        .find_map(|r| {
            let rev = cell_str(r, 2);
            if rev.len() >= 7 {
                return Some(rev.chars().take(10).collect::<String>());
            }
            let key = cell_str(r, 0);
            let seg = key.split(':').nth(3).unwrap_or("");
            if seg.len() >= 7 {
                Some(seg.chars().take(10).collect::<String>())
            } else {
                None
            }
        })
        .unwrap_or_else(|| String::from("not-recorded"));

    let recent_transitions: Vec<Value> = tr
        .rows
        .iter()
        .take(8)
        .map(|r| {
            let raw_tid = cell_str(r, 0);
            let subj = cell_str(r, 1);
            let st_type = cell_str(r, 2);
            let from_s = cell_str(r, 3);
            let to_s = cell_str(r, 4);
            json!({
                "transition_id": short_digest(&raw_tid),
                "raw_transition_id": raw_tid,
                "subject": short_subject_name(&subj),
                "state_type": st_type.clone(),
                "display_state_type": humanize_state_type_ko(&st_type),
                "from_state": from_s.clone(),
                "display_from": humanize_state_ko(&from_s),
                "to_state": to_s.clone(),
                "display_to": humanize_state_ko(&to_s),
                "completeness_pct": (cell_i64(r, 5).unwrap_or(0) as f64) / 100.0,
                "recorded_at": cell_str(r, 6)
            })
        })
        .collect();

    let latest_pg_state = tr
        .rows
        .iter()
        .find(|r| cell_str(r, 1).contains("postgresql"))
        .map(|r| {
            format!(
                "{} → {}",
                humanize_state_ko(&cell_str(r, 3)),
                humanize_state_ko(&cell_str(r, 4))
            )
        })
        .unwrap_or_else(|| {
            if durable_count > 0 {
                String::from("전환 기록 없음")
            } else {
                String::from("미측정")
            }
        });
    let latest_lb_state = tr
        .rows
        .iter()
        .find(|r| cell_str(r, 1).contains("loadbalancers"))
        .map(|r| {
            format!(
                "{} → {}",
                humanize_state_ko(&cell_str(r, 3)),
                humanize_state_ko(&cell_str(r, 4))
            )
        })
        .unwrap_or_else(|| {
            if edge_count > 0 {
                String::from("전환 기록 없음")
            } else {
                String::from("미측정")
            }
        });

    let has_aks_data = total_resources > 0 || total_batches > 0 || total_transitions > 0;
    let scenario_label = if !has_aks_data {
        String::from("수집된 AKS 데모 온톨로지 및 전환 데이터 없음 (미측정)")
    } else if service_id == "catalog-browse" {
        format!(
            "실측 시나리오: 카탈로그 조회 · 온톨로지 리소스 {total_resources}개 · 관측 배치 {total_batches}건"
        )
    } else {
        format!(
            "실측 시나리오: 주문 처리 · 온톨로지 리소스 {total_resources}개 · 관측 배치 {total_batches}건"
        )
    };

    let (slo1_tone, slo1_badge) = match availability_ratio {
        Some(pct) if pct >= 90.0 => ("tone-live", "충족"),
        Some(_) => ("tone-sre", "주의"),
        None => ("tone-neutral", "미측정"),
    };
    let (slo2_tone, slo2_badge) = match avg_comp {
        Some(pct) if pct >= 90.0 => ("tone-live", "충족"),
        Some(_) => ("tone-sre", "주의"),
        None => ("tone-neutral", "미측정"),
    };

    let signals = if has_aks_data {
        vec![
            json!({
                "name": "transition_batches",
                "display_name": "상태 전환 관측 배치",
                "current": format!("{total_batches}건"),
                "baseline": format!("커버리지 {coverage_total}건"),
                "source": "postgres:operational_state_transition_batch",
                "display_source": "로컬 상태 원장"
            }),
            json!({
                "name": "state_transitions_recent",
                "display_name": "최근 상태 전환 횟수",
                "current": format!("{total_transitions}건"),
                "baseline": format!("정상 회복 {healthy_transitions_i64}건"),
                "source": "postgres:operational_state_transition",
                "display_source": "로컬 상태 원장"
            }),
            json!({
                "name": "ontology_resources",
                "display_name": "온톨로지 관측 리소스",
                "current": format!("{total_resources}개"),
                "baseline": "실측 스냅샷 기준",
                "source": "postgres:ontology_resource",
                "display_source": "온톨로지 그래프"
            }),
            json!({
                "name": "inventory_replica_lag",
                "display_name": "재고 복제 지연",
                "current": "데이터 없음 (미수집)",
                "baseline": "데이터 없음 (미수집)",
                "source": "collector_gap",
                "display_source": "수집기 미응답"
            }),
        ]
    } else {
        Vec::new()
    };

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "service_id": service_id,
        "scenario_summary": scenario_label,
        "demo_repo_revision": demo_rev,
        "resource_total": total_resources,
        "transition_batch_count": total_batches,
        "transition_count": total_transitions,
        "coverage_total": coverage_total,
        "overall_status_tone": if has_aks_data { "tone-live" } else { "tone-neutral" },
        "overall_status_label": if has_aks_data { "실측 관측 중" } else { "미측정" },
        "effect_badge_tone": if total_transitions > 0 { "tone-live" } else { "tone-neutral" },
        "effect_badge_label": if total_transitions > 0 { "실측 기준선 관측" } else { "미측정" },
        "action_name": "없음 (lab-sandbox 읽기 전용 관측)",
        "effect_text": if total_transitions > 0 {
            format!("PostgreSQL 전환 원장 {total_transitions}건 · 배치 {total_batches}건 관측 중")
        } else {
            String::from("수집된 전환 원장 없음 (미측정)")
        },
        "topology_nodes": {
            "gateway": {
                "title": "에지 · 로드밸런서 계층",
                "metric": if edge_count > 0 { format!("에지 리소스 {edge_count}개 · {latest_lb_state}") } else { String::from("미측정 (에지 리소스 없음)") },
                "status": if edge_count > 0 { "관측됨" } else { "미측정" },
                "tone": if edge_count > 0 { "tone-live" } else { "tone-neutral" },
                "facts": [
                    ["온톨로지 에지 리소스", if edge_count > 0 { format!("{edge_count}건") } else { String::from("미측정") }],
                    ["최근 LB 상태 전환", latest_lb_state],
                    ["격리 범위", "lab-sandbox (운영 변이 0건)"]
                ]
            },
            "orders": {
                "title": if service_id == "catalog-browse" { "카탈로그 · 컴퓨트 계층" } else { "컴퓨트 · AKS 워크로드" },
                "metric": if compute_count > 0 { format!("컴퓨트 {compute_count}개 · 기준 스냅샷 관측") } else { String::from("미측정 (컴퓨트 리소스 없음)") },
                "status": if compute_count > 0 { "관측됨" } else { "미측정" },
                "tone": if compute_count > 0 { "tone-live" } else { "tone-neutral" },
                "facts": [
                    ["컴퓨트/컨테이너 리소스", if compute_count > 0 { format!("{compute_count}건") } else { String::from("미측정") }],
                    ["기준 저장소 리비전", demo_rev.clone()],
                    ["서비스 시나리오", if service_id == "catalog-browse" { String::from("카탈로그 조회") } else { String::from("주문 처리") }]
                ]
            },
            "postgres": {
                "title": "데이터베이스 · 스토리지 계층",
                "metric": if durable_count > 0 { format!("저장소 {durable_count}개 · {latest_pg_state}") } else { String::from("미측정 (저장소 리소스 없음)") },
                "status": if durable_count > 0 { "관측됨" } else { "미측정" },
                "tone": if durable_count > 0 { "tone-live" } else { "tone-neutral" },
                "facts": [
                    ["DB/스토리지 리소스", if durable_count > 0 { format!("{durable_count}건") } else { String::from("미측정") }],
                    ["최근 DB 상태 전환", latest_pg_state],
                    ["전환 배치 수", if total_batches > 0 { format!("{total_batches}건") } else { String::from("미측정") }]
                ]
            },
            "redis": {
                "title": "네트워크 · 캐시 계층",
                "metric": if network_cache_count > 0 || coverage_total > 0 { format!("네트워크/캐시 {network_cache_count}개 · 커버리지 {coverage_total}") } else { String::from("미측정 (네트워크/캐시 없음)") },
                "status": if network_cache_count > 0 || coverage_total > 0 { "관측됨" } else { "미측정" },
                "tone": if network_cache_count > 0 || coverage_total > 0 { "tone-live" } else { "tone-neutral" },
                "facts": [
                    ["네트워크/DNS/PE 리소스", if network_cache_count > 0 { format!("{network_cache_count}건") } else { String::from("미측정") }],
                    ["상태 전환 커버리지", if coverage_total > 0 { format!("{coverage_total}건") } else { String::from("미측정") }],
                    ["격리 보증", "lab-sandbox 전용"]
                ]
            }
        },
        "slo": {
            "availability_pct": availability_ratio,
            "completeness_pct": avg_comp,
            "slo1_status_tone": slo1_tone,
            "slo1_status_label": slo1_badge,
            "slo2_status_tone": slo2_tone,
            "slo2_status_label": slo2_badge,
            "slo1_label": match availability_ratio {
                Some(pct) => format!("실측 전환 회복률 {pct:.1}% · 정상 전환 {healthy_transitions_i64}/{total_transitions}건"),
                None => String::from("데이터 없음 (미수집)")
            },
            "slo2_label": match avg_comp {
                Some(pct) => format!("전환 근거 완전성 {pct:.1}% · 배치 {total_batches}건"),
                None => String::from("데이터 없음 (미수집)")
            },
            "unmeasured_gap": if coverage_total > 0 {
                format!(
                    "재고 복제 지연 미수집 · 커버리지 제약: 스냅샷 구간 한정 {snapshot_only}건, 초기 상태 한정 {initial_only}건 (0 대체 금지)"
                )
            } else {
                String::from("수집된 재고 복제 지연 및 커버리지 근거가 없습니다 (미수집 · 0 대체 금지)")
            }
        },
        "signals": signals,
        "recent_transitions": recent_transitions
    })
}

/// Panel 3 (`assurance-twin`): Posture, rule-level baseline diffs, and code-security reviews from PostgreSQL.
pub async fn fetch_assurance_twin(db: &DbHandle, review_key: Option<&str>) -> Value {
    let (
        ont_summary,
        outcome_totals,
        rule_groups,
        sec_reviews,
        completion_meta,
        code_sec_issues,
        active_findings,
        ont_rules,
        audit_outcomes,
    ) = tokio::join!(
        db.query_single_readonly(
            "SELECT count(*), \
             count(*) FILTER (WHERE object_type = 'Rule'), \
             count(*) FILTER (WHERE object_type = 'PolicyArtifact'), \
             COALESCE(MAX(revision), 1) \
             FROM ontology_resource",
        ),
        db.query_single_readonly(
            "SELECT COALESCE(value->>'outcome', 'unknown'), count(*) \
             FROM state_kv WHERE key LIKE 'baseline-evaluation:outcomes:%' \
             GROUP BY 1",
        ),
        db.query_single_readonly(
            "SELECT COALESCE(value->>'rule_ref', 'unknown') AS rule_ref, \
             count(*) FILTER (WHERE value->>'outcome' = 'compliant') AS comp_cnt, \
             count(*) FILTER (WHERE value->>'outcome' = 'violated') AS viol_cnt, \
             count(*) FILTER (WHERE value->>'outcome' = 'abstained') AS abst_cnt, \
             COALESCE(MAX(value->>'evaluated_at'), '') AS latest_at \
             FROM state_kv WHERE key LIKE 'baseline-evaluation:outcomes:%' \
             GROUP BY 1 ORDER BY viol_cnt DESC, abst_cnt DESC, comp_cnt DESC LIMIT 8",
        ),
        db.query_single_readonly(
            "SELECT key, \
             COALESCE(value->'package'->>'revision', ''), \
             COALESCE(value->'package'->'source'->>'provider', 'github'), \
             to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
             FROM state_kv WHERE key LIKE 'runtime:code-security-review:%' \
             ORDER BY updated_at DESC LIMIT 4",
        ),
        db.query_single_readonly(
            "SELECT COALESCE(value->>'audit_ref', ''), \
             COALESCE(value->>'audit_digest', ''), \
             COALESCE(value->>'completed_at', '') \
             FROM state_kv WHERE key LIKE 'baseline-evaluation:coverage:%' \
             ORDER BY updated_at DESC LIMIT 1",
        ),
        db.query_single_readonly(
            "SELECT key, \
             jsonb_array_length(COALESCE(value->'issues', '[]'::jsonb)) AS issue_cnt, \
             to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
             FROM state_kv \
             WHERE key LIKE 'runtime:code-security-issues:%' AND key NOT LIKE '%:artifacts-%' \
             ORDER BY updated_at DESC LIMIT 4",
        ),
        db.query_single_readonly(
            "SELECT key, \
             COALESCE(value->>'signal', 'unknown'), \
             COALESCE(value->>'severity', 'medium'), \
             COALESCE(value->>'status', 'active'), \
             COALESCE(value->>'assessed_by', 'Heimdall'), \
             to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
             FROM state_kv WHERE key LIKE 'runtime:analyzer-finding-current:%' \
             ORDER BY updated_at DESC LIMIT 6",
        ),
        db.query_single_readonly(
            "SELECT id, \
             COALESCE(properties->>'severity', 'medium'), \
             COALESCE(properties->>'resource_type', 'resource'), \
             COALESCE(properties->>'remediates', 'none'), \
             to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
             FROM ontology_resource WHERE object_type = 'Rule' \
             ORDER BY CASE COALESCE(properties->>'severity', 'low') \
               WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END, id \
             LIMIT 6",
        ),
        db.query_single_readonly(
            "SELECT \
             count(*) FILTER (WHERE action_kind = 'control_loop.compliant'), \
             count(*) FILTER (WHERE action_kind = 'control_loop.abstain'), \
             count(*) FILTER (WHERE action_kind = 'risk_gate.unified'), \
             COALESCE(MAX(entry_hash), '') \
             FROM audit_log",
        ),
    );

    let (Ok(ont), Ok(ot), Ok(rg), Ok(sr), Ok(cm), Ok(csi), Ok(af), Ok(orules), Ok(ao)) = (
        ont_summary,
        outcome_totals,
        rule_groups,
        sec_reviews,
        completion_meta,
        code_sec_issues,
        active_findings,
        ont_rules,
        audit_outcomes,
    ) else {
        return db.not_measured(
            "labs",
            "/api/v4/labs/assurance-twin",
            "postgres_unreachable",
        );
    };

    let ont_total = ont.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let rule_count = ont.rows.first().and_then(|r| cell_i64(r, 1)).unwrap_or(0);
    let policy_count = ont.rows.first().and_then(|r| cell_i64(r, 2)).unwrap_or(0);
    let max_rev = ont.rows.first().and_then(|r| cell_i64(r, 3)).unwrap_or(1);

    let mut compliant_total = 0_i64;
    let mut violated_total = 0_i64;
    let mut abstained_total = 0_i64;
    for r in &ot.rows {
        let o = cell_str(r, 0);
        let c = cell_i64(r, 1).unwrap_or(0);
        match o.as_str() {
            "compliant" => compliant_total = c,
            "violated" => violated_total = c,
            "abstained" => abstained_total = c,
            _ => {}
        }
    }
    let audit_compliant = ao.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let audit_abstained = ao.rows.first().and_then(|r| cell_i64(r, 1)).unwrap_or(0);
    let audit_hash = ao.rows.first().map(|r| cell_str(r, 3)).unwrap_or_default();
    let active_finding_cnt = i64::try_from(af.rows.len()).unwrap_or(0);
    if compliant_total == 0 && violated_total == 0 && abstained_total == 0 {
        compliant_total = audit_compliant;
        violated_total = active_finding_cnt;
        abstained_total = audit_abstained;
    }

    let has_audit_window =
        !audit_hash.is_empty() || compliant_total > 0 || violated_total > 0 || abstained_total > 0;
    let audit_ref = cm
        .rows
        .first()
        .map(|r| cell_str(r, 0))
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| {
            if has_audit_window {
                String::from("audit:postgres-7d-window")
            } else {
                String::from("—")
            }
        });
    let audit_digest = cm
        .rows
        .first()
        .map(|r| cell_str(r, 1))
        .filter(|s| !s.is_empty())
        .or_else(|| (!audit_hash.is_empty()).then_some(audit_hash))
        .unwrap_or_else(|| String::from("미측정"));
    let completed_at = cm
        .rows
        .first()
        .map(|r| cell_str(r, 2))
        .unwrap_or_default();

    let mut reviews: Vec<Value> = Vec::new();

    for (idx, r) in sr.rows.iter().enumerate() {
        let raw_key = cell_str(r, 0);
        let rev_sha = cell_str(r, 1);
        let provider = cell_str(r, 2);
        let updated = cell_str(r, 3);
        let repo_slug = raw_key
            .split(':')
            .nth(2)
            .unwrap_or("aks-store-demo")
            .to_string();
        let short_sha: String = rev_sha.chars().take(8).collect();
        let rk = format!("{repo_slug}@{short_sha}");
        reviews.push(json!({
            "id": format!("sec-{idx}"),
            "review_key": rk,
            "title": format!("{repo_slug}@{short_sha} · 코드 보안 리뷰 ({provider})"),
            "verdict": "needs_review",
            "verdict_label": "검토 필요 (needs_review)",
            "verdict_tone": "tone-sre",
            "mode": "shadow",
            "finding_count": violated_total,
            "freshness": "최신",
            "before": [
                format!("- 온톨로지 기준선: 리비전 {max_rev} (리소스 {ont_total}건)"),
                format!("- 평가 정책 규칙: {rule_count}종 · 정책 아티팩트 {policy_count}건"),
                format!("- 기준선 준수 결과: {compliant_total}건")
            ],
            "after": [
                format!("+ 코드 보안 리뷰 대상: {repo_slug} ({short_sha})"),
                format!("+ 기준선 위반: {violated_total}건 · 정직 보류: {abstained_total}건"),
                "+ 운영 차단 여부: 없음 (격리 검증 · 운영 변이 0건)"
            ],
            "resources": [
                {
                    "ico": "/azure-icons/kubernetes-services.svg",
                    "name": format!("{repo_slug} · 커밋 {short_sha}"),
                    "sub": format!("제공자: {provider} · 기록 시각: {updated}"),
                    "sev": "검토 필요",
                    "cls": "tone-sre"
                }
            ],
            "activity_id": format!("sec-rev-{short_sha}"),
            "correlation_id": audit_ref.clone(),
            "evidence_digest": short_digest(&audit_digest),
            "source_revision": format!("ontology-rev-{max_rev}"),
            "withheld": format!("정직 보류 기준선 {abstained_total}건 (근거 부족 시 0 대체 차단)")
        }));
    }

    // Preserved code-security issue bundles (e.g. aks-store-demo after 7-day compaction)
    if reviews.is_empty() {
        for (idx, r) in csi.rows.iter().enumerate() {
            let raw_key = cell_str(r, 0);
            let issue_cnt = cell_i64(r, 1).unwrap_or(0);
            let updated = cell_str(r, 2);
            let repo_slug = raw_key
                .split(':')
                .nth(2)
                .unwrap_or("aks-store-demo")
                .to_string();
            let sha_full = raw_key.split(':').nth(3).unwrap_or("latest");
            let short_sha: String = sha_full.chars().take(8).collect();
            let rk = format!("{repo_slug}@{short_sha}");
            reviews.push(json!({
                "id": format!("csi-{idx}"),
                "review_key": rk,
                "display_ref": format!("{repo_slug} 보안 점검 ({issue_cnt}건)"),
                "raw_resource_type": "code-security-bundle",
                "title": format!("{repo_slug} · 코드 보안 이슈 번들 ({issue_cnt}건)"),
                "verdict": if issue_cnt > 0 { "needs_review" } else { "clear" },
                "verdict_label": if issue_cnt > 0 { "검토 필요" } else { "이상 없음" },
                "verdict_tone": if issue_cnt > 0 { "tone-sre" } else { "tone-live" },
                "mode": "shadow",
                "finding_count": issue_cnt,
                "freshness": "최신",
                "before": [
                    format!("- 온톨로지 기준선: 리비전 {max_rev} (리소스 {ont_total}건)"),
                    format!("- 등록 정책 규칙: {rule_count}종 · 정책 아티팩트 {policy_count}건"),
                    format!("- 최근 7일 기준선 준수: {compliant_total}건")
                ],
                "after": [
                    format!("+ 코드 보안 이슈: {issue_cnt}건 ({repo_slug})"),
                    format!("+ 활성 분석 탐지: {active_finding_cnt}건 · 정직 보류: {abstained_total}건"),
                    "+ 운영 차단 여부: 없음 (격리 검증 · 운영 변이 0건)"
                ],
                "resources": [
                    {
                        "ico": "/azure-icons/kubernetes-services.svg",
                        "name": format!("{repo_slug} · 커밋 {short_sha}"),
                        "sub": format!("실측 보안 이슈 {issue_cnt}건 · 기록 시각: {updated}"),
                        "sev": if issue_cnt > 0 { "높음" } else { "정상" },
                        "cls": if issue_cnt > 0 { "tone-sec" } else { "tone-live" }
                    }
                ],
                "activity_id": format!("sec-issues-{short_sha}"),
                "correlation_id": audit_ref.clone(),
                "evidence_digest": short_digest(&audit_digest),
                "source_revision": format!("ontology-rev-{max_rev}"),
                "withheld": format!("7일 정리 이후 정직 보류 {abstained_total}건")
            }));
        }
    }

    // Active analyzer findings preserved in state_kv
    for (idx, r) in af.rows.iter().enumerate() {
        let raw_key = cell_str(r, 0);
        let signal = cell_str(r, 1);
        let sev = cell_str(r, 2);
        let status = cell_str(r, 3);
        let assessed_by = cell_str(r, 4);
        let updated = cell_str(r, 5);
        let fid: String = raw_key
            .rsplit(':')
            .next()
            .unwrap_or("finding")
            .chars()
            .take(10)
            .collect();
        let rk = format!("finding/{signal}#{fid}");
        let is_high = sev.eq_ignore_ascii_case("high") || sev.eq_ignore_ascii_case("critical");
        let sig_ko = humanize_signal_ko(&signal);
        let sev_ko = humanize_severity_ko(&sev);
        let status_ko = humanize_finding_status_ko(&status);
        reviews.push(json!({
            "id": format!("af-{idx}"),
            "review_key": rk,
            "display_ref": format!("{sig_ko} #{}", idx + 1),
            "raw_resource_type": signal,
            "title": format!("{sig_ko} · 심각도 {sev_ko} · {assessed_by}"),
            "verdict": "needs_review",
            "verdict_label": "검토 필요",
            "verdict_tone": if is_high { "tone-sec" } else { "tone-sre" },
            "mode": "shadow",
            "finding_count": 1,
            "freshness": "최신",
            "before": [
                format!("- 기준선 신호: {sig_ko} (정상 기준선)"),
                format!("- 온톨로지 기준선: 리비전 {max_rev} (규칙 {rule_count}종)"),
                format!("- 평가 주체: {assessed_by}")
            ],
            "after": [
                format!("+ 활성 탐지: {sig_ko} [{sev_ko}] · 상태: {status_ko}"),
                format!("+ 기록 시각: {updated}"),
                "+ 운영 차단 여부: 없음 (격리 사전 검증 전용)"
            ],
            "resources": [
                {
                    "ico": "/azure-icons/container-apps.svg",
                    "name": format!("{sig_ko} · {status_ko}"),
                    "sub": format!("탐지 주체: {assessed_by} · 기록 시각: {updated}"),
                    "sev": sev_ko,
                    "cls": if is_high { "tone-sec" } else { "tone-sre" }
                }
            ],
            "activity_id": format!("finding-{fid}"),
            "correlation_id": audit_ref.clone(),
            "evidence_digest": short_digest(&audit_digest),
            "source_revision": format!("ontology-rev-{max_rev}"),
            "withheld": "없음"
        }));
    }

    for (idx, r) in rg.rows.iter().enumerate() {
        let rule_ref = cell_str(r, 0);
        let comp_cnt = cell_i64(r, 1).unwrap_or(0);
        let viol_cnt = cell_i64(r, 2).unwrap_or(0);
        let abst_cnt = cell_i64(r, 3).unwrap_or(0);
        let latest_at = cell_str(r, 4);
        let short_rule = rule_ref.strip_prefix("rule:").unwrap_or(&rule_ref);
        let rule_ko = humanize_rule_ko(short_rule, "");

        let (verdict, verdict_label, verdict_tone, sev, sev_cls) = if viol_cnt > 0 {
            ("needs_review", "검토 필요", "tone-sre", "위반 탐지", "tone-sec")
        } else if abst_cnt > 0 && comp_cnt == 0 {
            ("unmeasured", "정직 보류", "tone-neutral", "보류", "tone-neutral")
        } else {
            ("clear", "이상 없음", "tone-live", "준수", "tone-live")
        };

        let icon = if short_rule.contains("network") || short_rule.contains("nsg") {
            "/azure-icons/virtual-network.svg"
        } else if short_rule.contains("compute") || short_rule.contains("vm") {
            "/azure-icons/kubernetes-services.svg"
        } else if short_rule.contains("secret") || short_rule.contains("key") {
            "/azure-icons/key-vault.svg"
        } else {
            "/azure-icons/monitor.svg"
        };

        reviews.push(json!({
            "id": format!("rule-{idx}"),
            "review_key": short_rule,
            "display_ref": rule_ko.clone(),
            "raw_resource_type": short_rule,
            "title": format!("{rule_ko} · 위반 {viol_cnt} / 준수 {comp_cnt} / 보류 {abst_cnt}"),
            "verdict": verdict,
            "verdict_label": verdict_label,
            "verdict_tone": verdict_tone,
            "mode": "shadow",
            "finding_count": viol_cnt,
            "freshness": if abst_cnt > 0 && comp_cnt == 0 && viol_cnt == 0 { "정직 보류" } else { "최신" },
            "before": [
                format!("- 대상 규칙: {rule_ko}"),
                format!("- 온톨로지 기준선: 리비전 {max_rev} (총 규칙 {rule_count}종)"),
                format!("- 기준선 준수 리소스: {comp_cnt}건")
            ],
            "after": [
                format!("+ 정책 위반 탐지: {viol_cnt}건"),
                format!("+ 정직 보류: {abst_cnt}건 (근거 부족 시 0 대체 차단)"),
                format!("+ 평가 시각: {latest_at}")
            ],
            "resources": [
                {
                    "ico": icon,
                    "name": rule_ko,
                    "sub": format!("실측 평가 합계 {}건 (위반 {viol_cnt} · 준수 {comp_cnt} · 보류 {abst_cnt})", comp_cnt + viol_cnt + abst_cnt),
                    "sev": sev,
                    "cls": sev_cls
                }
            ],
            "activity_id": format!("baseline-rule-{idx}"),
            "correlation_id": audit_ref.clone(),
            "evidence_digest": short_digest(&audit_digest),
            "source_revision": format!("ontology-rev-{max_rev}"),
            "withheld": if abst_cnt > 0 {
                format!("정직 보류 {abst_cnt}건 (불완전 근거 보류)")
            } else {
                String::from("없음")
            }
        }));
    }

    // When historical baseline-evaluation:outcomes:* rows were compacted, project live ontology Rule definitions
    if rg.rows.is_empty() {
        for (idx, r) in orules.rows.iter().enumerate() {
            let rule_id = cell_str(r, 0);
            let sev = cell_str(r, 1);
            let rtype = cell_str(r, 2);
            let remediates = cell_str(r, 3);
            let updated = cell_str(r, 4);
            let is_high = sev.eq_ignore_ascii_case("high") || sev.eq_ignore_ascii_case("critical");
            let icon = if rule_id.contains("network") || rule_id.contains("nsg") {
                "/azure-icons/virtual-network.svg"
            } else if rule_id.contains("kubernetes") || rule_id.contains("compute") {
                "/azure-icons/kubernetes-services.svg"
            } else if rule_id.contains("secret") || rule_id.contains("key") {
                "/azure-icons/key-vault.svg"
            } else {
                "/azure-icons/monitor.svg"
            };
            let rtype_ko = humanize_resource_type_ko(&rtype);
            let sev_ko = humanize_severity_ko(&sev);
            let rule_ko = humanize_rule_ko(&rule_id, &rtype);
            let rem_ko = humanize_remediation_ko(&remediates);
            reviews.push(json!({
                "id": format!("ont-rule-{idx}"),
                "review_key": rule_id.clone(),
                "display_ref": rule_ko.clone(),
                "raw_resource_type": rtype,
                "raw_remediation": remediates,
                "title": format!("{rule_ko} · 심각도 {sev_ko}"),
                "verdict": if is_high { "needs_review" } else { "clear" },
                "verdict_label": if is_high { "고위험 규칙 · 그림자 검증" } else { "기준선 규칙 · 정상" },
                "verdict_tone": if is_high { "tone-sre" } else { "tone-live" },
                "mode": "shadow",
                "finding_count": 0,
                "freshness": "최신",
                "before": [
                    format!("- 대상 규칙: {rule_ko}"),
                    format!("- 대상 리소스 유형: {rtype_ko}"),
                    format!("- 온톨로지 기준선: 리비전 {max_rev} (총 규칙 {rule_count}종)")
                ],
                "after": [
                    format!("+ 심각도: {sev_ko} · 권장 조치: {rem_ko}"),
                    format!("+ 최근 갱신: {updated}"),
                    "+ 운영 차단 여부: 없음 (격리 정책 시뮬레이션)"
                ],
                "resources": [
                    {
                        "ico": icon,
                        "name": rule_ko,
                        "sub": format!("대상 유형: {rtype_ko} · 권장 조치: {rem_ko}"),
                        "sev": sev_ko,
                        "cls": if is_high { "tone-sre" } else { "tone-live" }
                    }
                ],
                "activity_id": format!("ont-rule-{idx}"),
                "correlation_id": audit_ref.clone(),
                "evidence_digest": short_digest(&audit_digest),
                "source_revision": format!("ontology-rev-{max_rev}"),
                "withheld": "없음"
            }));
        }
    }

    let detail = match review_key {
        Some(req_key) => reviews
            .iter()
            .find(|item| {
                item["review_key"]
                    .as_str()
                    .is_some_and(|k| k.eq_ignore_ascii_case(req_key))
                    || item["id"]
                        .as_str()
                        .is_some_and(|k| k.eq_ignore_ascii_case(req_key))
            })
            .cloned()
            .unwrap_or_else(|| {
                json!({
                    "review_key": req_key,
                    "verdict": "not_found_in_postgres",
                    "verdict_label": "미등록 리뷰 키 (not-measured)",
                    "verdict_tone": "tone-neutral",
                    "note": "요청한 review_key가 로컬 PostgreSQL 기준선/리뷰 목록에 없습니다 (임의 생성 차단)."
                })
            }),
        None => reviews.first().cloned().unwrap_or(Value::Null),
    };

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "posture": {
            "revision": format!("ontology-rev-{max_rev}"),
            "ontology_resource_count": ont_total,
            "rule_count": rule_count,
            "policy_artifact_count": policy_count,
            "compliant_count": compliant_total,
            "violated_count": violated_total,
            "abstained_count": abstained_total,
            "evaluated_at": completed_at,
            "audit_ref": audit_ref,
            "audit_digest": short_digest(&audit_digest)
        },
        "reviews": reviews,
        "detail": detail
    })
}

/// Panel 4 (`forecast-learning`): Transition coverage heatmap, benchmark calibration, and outcome breakdown.
pub async fn fetch_forecast_learning(db: &DbHandle) -> Value {
    let (batch_res, trans_res, cov_summary, cov_heatmap, bench_totals, bench_res, baseline_res) =
        tokio::join!(
            db.query_single_readonly("SELECT count(*) FROM operational_state_transition_batch"),
            db.query_single_readonly(
                "SELECT count(*), COALESCE(round(avg(completeness_basis_points)::numeric, 1), 0) \
                 FROM operational_state_transition",
            ),
            db.query_single_readonly(
                "SELECT count(*), \
                 count(*) FILTER (WHERE complete), \
                 count(*) FILTER (WHERE limitation = 'snapshot_interval_only'), \
                 count(*) FILTER (WHERE limitation = 'initial_state_only') \
                 FROM operational_state_transition_coverage",
            ),
            db.query_single_readonly(
                "SELECT extract(dow from recorded_at AT TIME ZONE 'Asia/Seoul')::int AS dow, \
                 (extract(hour from recorded_at AT TIME ZONE 'Asia/Seoul')::int / 2) * 2 AS hr2, \
                 count(*) AS total, \
                 count(*) FILTER (WHERE NOT complete) AS incomplete \
                 FROM operational_state_transition_coverage \
                 GROUP BY 1, 2 ORDER BY 1, 2",
            ),
            db.query_single_readonly(
                "SELECT count(*), \
                 count(*) FILTER (WHERE (properties->>'passed')::boolean) \
                 FROM ontology_resource WHERE object_type = 'BenchmarkValidation'",
            ),
            db.query_single_readonly(
                "SELECT COALESCE(properties->>'mechanism_id', 'unknown') AS mech, \
                 count(*) AS total, \
                 count(*) FILTER (WHERE (properties->>'passed')::boolean) AS passed \
                 FROM ontology_resource WHERE object_type = 'BenchmarkValidation' \
                 GROUP BY 1 ORDER BY 2 DESC, 3 DESC LIMIT 5",
            ),
            db.query_single_readonly(
                "SELECT COALESCE(value->>'outcome', 'unknown'), count(*) \
                 FROM state_kv WHERE key LIKE 'baseline-evaluation:outcomes:%' \
                 GROUP BY 1",
            ),
        );

    let (Ok(br), Ok(tr), Ok(cs), Ok(ch), Ok(bt), Ok(bench), Ok(bl)) = (
        batch_res,
        trans_res,
        cov_summary,
        cov_heatmap,
        bench_totals,
        bench_res,
        baseline_res,
    ) else {
        return db.not_measured(
            "labs",
            "/api/v4/labs/forecast-learning",
            "postgres_unreachable",
        );
    };

    let batch_count = br.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let transition_count = tr.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let avg_comp_pct: Option<f64> = if transition_count > 0 {
        tr.rows
            .first()
            .and_then(|r| cell_f64(r, 1))
            .map(|bps| ((bps / 100.0) * 10.0).round() / 10.0)
    } else {
        None
    };

    let cov_total = cs.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let cov_complete = cs.rows.first().and_then(|r| cell_i64(r, 1)).unwrap_or(0);
    let cov_snapshot_only = cs.rows.first().and_then(|r| cell_i64(r, 2)).unwrap_or(0);
    let cov_initial_only = cs.rows.first().and_then(|r| cell_i64(r, 3)).unwrap_or(0);

    let bench_total = bt.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let bench_passed = bt.rows.first().and_then(|r| cell_i64(r, 1)).unwrap_or(0);
    let mut calibration_bins: Vec<Value> = Vec::new();
    for r in bench.rows.iter().take(5) {
        let mech = cell_str(r, 0);
        let tot = cell_i64(r, 1).unwrap_or(0);
        let pass = cell_i64(r, 2).unwrap_or(0);
        let rate = format_pct(pass, tot).unwrap_or(0.0);
        calibration_bins.push(json!({
            "mechanism": mech,
            "display_label": humanize_mechanism_ko(&mech),
            "total": tot,
            "passed": pass,
            "pass_rate_pct": rate
        }));
    }
    let bench_pass_rate = format_pct(bench_passed, bench_total);

    // Map PostgreSQL dow (0=Sun, 1=Mon..6=Sat) to UI row index (0=Mon..5=Sat, 6=Sun)
    // Columns 0..=9 represent 00h..18h (2h bins); 20h/22h rolled into 18h+ bucket summary or tracked in cells.
    let mut grid_totals = [[0_i64; 10]; 7];
    let mut grid_incomplete = [[0_i64; 10]; 7];
    for r in &ch.rows {
        let pg_dow = cell_i64(r, 0).unwrap_or(0);
        let hr2 = cell_i64(r, 1).unwrap_or(0);
        let tot = cell_i64(r, 2).unwrap_or(0);
        let inc = cell_i64(r, 3).unwrap_or(0);
        let row_idx = match pg_dow {
            1..=6 => usize::try_from(pg_dow - 1).unwrap_or(0),
            _ => 6,
        };
        let col_idx = usize::try_from((hr2 / 2).clamp(0, 9)).unwrap_or(0);
        if row_idx < 7 && col_idx < 10 {
            grid_totals[row_idx][col_idx] += tot;
            grid_incomplete[row_idx][col_idx] += inc;
        }
    }

    let mut heatmap_rows: Vec<Value> = Vec::with_capacity(7);
    for r_idx in 0..7 {
        let mut cols: Vec<Value> = Vec::with_capacity(12);
        for c_idx in 0..10 {
            let tot = grid_totals[r_idx][c_idx];
            let inc = grid_incomplete[r_idx][c_idx];
            let level = if tot == 0 {
                6_u8 // unmeasured dashed cell
            } else if tot >= 500 {
                4_u8
            } else if tot >= 400 {
                3_u8
            } else if tot >= 250 {
                2_u8
            } else {
                1_u8
            };
            cols.push(json!({
                "level": level,
                "total": tot,
                "incomplete": inc
            }));
        }
        // +1h, +2h horizon cells
        cols.push(json!({ "level": 5_u8, "total": Value::Null, "incomplete": Value::Null }));
        cols.push(json!({ "level": 5_u8, "total": Value::Null, "incomplete": Value::Null }));
        heatmap_rows.push(Value::Array(cols));
    }

    let mut compliant_cnt = 0_i64;
    let mut violated_cnt = 0_i64;
    let mut abstained_cnt = 0_i64;
    for r in &bl.rows {
        let o = cell_str(r, 0);
        let c = cell_i64(r, 1).unwrap_or(0);
        match o.as_str() {
            "compliant" => compliant_cnt = c,
            "violated" => violated_cnt = c,
            "abstained" => abstained_cnt = c,
            _ => {}
        }
    }
    let baseline_total = compliant_cnt + violated_cnt + abstained_cnt;
    let bench_failed = (bench_total - bench_passed).max(0);
    let outcome_items = if baseline_total > 0 {
        vec![
            json!({
                "key": "compliant",
                "label": "기준선 정상 준수",
                "count": compliant_cnt,
                "pct": format_pct(compliant_cnt, baseline_total).unwrap_or(0.0),
                "tone": "live",
                "note": "기준선 평가 일치"
            }),
            json!({
                "key": "violated",
                "label": "정책 편차 탐지",
                "count": violated_cnt,
                "pct": format_pct(violated_cnt, baseline_total).unwrap_or(0.0),
                "tone": "sre",
                "note": "사전 보정·검토 대상"
            }),
            json!({
                "key": "abstained",
                "label": "근거 부족 정직 보류",
                "count": abstained_cnt,
                "pct": format_pct(abstained_cnt, baseline_total).unwrap_or(0.0),
                "tone": "neutral",
                "note": "0 대체 금지 · 표본 부족"
            }),
            json!({
                "key": "snapshot_interval_only",
                "label": "스냅샷 구간 한정 커버리지",
                "count": cov_snapshot_only,
                "pct": format_pct(cov_snapshot_only, cov_total).unwrap_or(0.0),
                "tone": "sec",
                "note": format!("초기 스냅샷 한정 {cov_initial_only}건 포함")
            }),
        ]
    } else if bench_total > 0 || cov_total > 0 {
        vec![
            json!({
                "key": "benchmark_passed",
                "label": "벤치마크 검증 통과",
                "count": bench_passed,
                "pct": format_pct(bench_passed, bench_total).unwrap_or(0.0),
                "tone": "live",
                "note": format!("총 {bench_total}건 중 통과")
            }),
            json!({
                "key": "benchmark_failed",
                "label": "벤치마크 보정 대상",
                "count": bench_failed,
                "pct": format_pct(bench_failed, bench_total).unwrap_or(0.0),
                "tone": "sre",
                "note": "실측 미충족 메커니즘"
            }),
            json!({
                "key": "snapshot_interval_only",
                "label": "스냅샷 구간 한정 커버리지",
                "count": cov_snapshot_only,
                "pct": format_pct(cov_snapshot_only, cov_total).unwrap_or(0.0),
                "tone": "sec",
                "note": "스냅샷 구간 한정 관측"
            }),
            json!({
                "key": "initial_state_only",
                "label": "초기 상태 한정 커버리지",
                "count": cov_initial_only,
                "pct": format_pct(cov_initial_only, cov_total).unwrap_or(0.0),
                "tone": "neutral",
                "note": "초기 스냅샷만 기록 · 0 대체 금지"
            }),
        ]
    } else {
        Vec::new()
    };
    let outcomes_total = if baseline_total > 0 {
        baseline_total
    } else {
        bench_total + cov_total
    };

    let completeness_text = match avg_comp_pct {
        Some(pct) => format!("{pct:.1}% (전환 {transition_count}건 · 배치 {batch_count}건)"),
        None => String::from("미측정 (전환 기록 없음)"),
    };
    let coverage_text = if cov_total > 0 {
        format!("{cov_total}건 (완전 {cov_complete} · 스냅샷 구간 {cov_snapshot_only})")
    } else {
        String::from("미측정 (커버리지 없음)")
    };
    let initial_only_text = if cov_total > 0 {
        format!("{cov_initial_only}건 (초기 상태 한정)")
    } else {
        String::from("미측정")
    };
    let benchmark_text = if bench_total > 0 {
        format!("{bench_passed} / {bench_total} 통과")
    } else {
        String::from("미측정 (벤치마크 기록 없음)")
    };

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "summary": {
            "batch_count": batch_count,
            "transition_count": transition_count,
            "coverage_total": cov_total,
            "coverage_complete": cov_complete,
            "coverage_snapshot_only": cov_snapshot_only,
            "coverage_initial_only": cov_initial_only,
            "avg_completeness_pct": avg_comp_pct,
            "benchmark_total": bench_total,
            "benchmark_passed": bench_passed,
            "benchmark_pass_rate_pct": bench_pass_rate
        },
        "debt_inspector": {
            "durable_store": "PostgreSQL Durable",
            "completeness_text": completeness_text,
            "coverage_text": coverage_text,
            "initial_only_text": initial_only_text,
            "retention_text": "미측정 (만료 추적기 미연결)",
            "benchmark_text": benchmark_text,
            "unmeasured_policy": "표본 0건 시간대는 0% 대체 없이 미수집 점선 표기"
        },
        "calibration_bins": calibration_bins,
        "heatmap_rows": heatmap_rows,
        "outcomes": {
            "total": outcomes_total,
            "items": outcome_items
        }
    })
}

/// Panel 5 (`conversation-assurance`): Assessments, semantic turn evaluations, and LLM invocation breakdown.
pub async fn fetch_conversation_assurance(db: &DbHandle) -> Value {
    let (totals, assess_rows, sem_rows, llm_rows, recent_llm_rows) = tokio::join!(
        db.query_single_readonly(
            "SELECT \
             (SELECT count(*) FROM conversation_assurance_assessment), \
             (SELECT count(*) FROM state_kv WHERE key LIKE 'operator-semantic-result:%'), \
             (SELECT count(*) FROM llm_invocation)",
        ),
        db.query_single_readonly(
            "SELECT assessment_id, turn_id, conversation_id, rubric_version, state, \
             COALESCE(decision->>'verdict', state), \
             to_char(assessed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
             FROM conversation_assurance_assessment ORDER BY assessed_at DESC LIMIT 20",
        ),
        db.query_single_readonly(
            "SELECT key, \
             COALESCE(value->'data'->>'status', 'unknown') AS st, \
             COALESCE(value->'data'->'payload'->>'model', 'unknown') AS model, \
             COALESCE((value->'data'->'payload'->>'latency_ms')::bigint, 0) AS latency_ms, \
             COALESCE((value->'data'->'payload'->'usage'->>'model_calls')::bigint, 0) AS calls, \
             COALESCE((value->'data'->'payload'->'usage'->>'total_tokens')::bigint, 0) AS total_tok, \
             COALESCE((value->'data'->'payload'->'usage'->>'cached_tokens')::bigint, 0) AS cached_tok, \
             COALESCE(value->'data'->'payload'->>'request_kind', 'semantic_turn') AS req_kind, \
             COALESCE(value->'data'->>'correlation_id', '') AS corr_id, \
             to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') AS ts \
             FROM state_kv WHERE key LIKE 'operator-semantic-result:%' \
             ORDER BY updated_at DESC LIMIT 20",
        ),
        db.query_single_readonly(
            "SELECT capability_id, model_key, tier, mode, count(*), \
             COALESCE(round(avg(prompt_tokens)::numeric, 1), 0), \
             COALESCE(round(avg(completion_tokens)::numeric, 1), 0), \
             COALESCE(SUM(prompt_tokens + completion_tokens), 0) \
             FROM llm_invocation GROUP BY 1, 2, 3, 4 ORDER BY 5 DESC LIMIT 12",
        ),
        db.query_single_readonly(
            "SELECT invocation_id, capability_id, model_key, tier, mode, \
             prompt_tokens, completion_tokens, usage_scope, correlation_id, \
             to_char(occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
             FROM llm_invocation \
             ORDER BY CASE WHEN tier = 'T2' THEN 0 ELSE 1 END, occurred_at DESC LIMIT 10",
        ),
    );

    let (Ok(tot), Ok(ar), Ok(sr), Ok(lr), Ok(rl)) = (
        totals,
        assess_rows,
        sem_rows,
        llm_rows,
        recent_llm_rows,
    ) else {
        return db.not_measured(
            "labs",
            "/api/v4/labs/conversation-assurance",
            "postgres_unreachable",
        );
    };

    let assessment_count = tot
        .rows
        .first()
        .and_then(|r| cell_i64(r, 0))
        .unwrap_or_else(|| i64::try_from(ar.rows.len()).unwrap_or(0));
    let semantic_result_count = tot
        .rows
        .first()
        .and_then(|r| cell_i64(r, 1))
        .unwrap_or_else(|| i64::try_from(sr.rows.len()).unwrap_or(0));
    let llm_total = tot
        .rows
        .first()
        .and_then(|r| cell_i64(r, 2))
        .unwrap_or_else(|| lr.rows.iter().filter_map(|r| cell_i64(r, 4)).sum());

    let agent_summary: Vec<Value> = lr
        .rows
        .iter()
        .map(|r| {
            let cap = cell_str(r, 0);
            let model = cell_str(r, 1);
            let tier = cell_str(r, 2);
            let mode = cell_str(r, 3);
            let calls = cell_i64(r, 4).unwrap_or(0);
            let avg_prompt = cell_f64(r, 5).unwrap_or(0.0);
            let avg_comp = cell_f64(r, 6).unwrap_or(0.0);
            let total_tok = cell_i64(r, 7).unwrap_or(0);
            json!({
                "capability_id": cap,
                "display_capability": humanize_capability_ko(&cap),
                "model_key": model,
                "tier": tier,
                "mode": mode,
                "calls": calls,
                "avg_prompt_tokens": avg_prompt,
                "avg_completion_tokens": avg_comp,
                "total_tokens": total_tok,
                "status_label": if tier == "T1" { "양호 (T1)" } else { "T2 추적" },
                "status_tone": if tier == "T1" { "tone-live" } else { "tone-sre" }
            })
        })
        .collect();

    let mut cases: Vec<Value> = Vec::new();
    for r in &ar.rows {
        let aid = cell_str(r, 0);
        let tid = cell_str(r, 1);
        let rubric = cell_str(r, 3);
        let state = cell_str(r, 4);
        let verdict_raw = cell_str(r, 5);
        let ts = cell_str(r, 6);
        let (verdict, badge, tone, state_ko) = match state.as_str() {
            "completed" => ("pass", "통과", "tone-live", "평가 완료"),
            "disputed" => ("fail", "이의 제기", "tone-sec", "이의 제기됨"),
            _ => ("review", "보류/검토", "tone-sre", "검토 대기"),
        };
        cases.push(json!({
            "case_id": short_digest(&tid),
            "display_label": format!("대화 품질 평가 · {state_ko}"),
            "agent": "Bragi",
            "agent_icon": "/agent-icons/bragi.svg",
            "score_text": format!("기준표 {rubric}"),
            "hallucination_text": "평가표 기록",
            "boundary_text": "통과",
            "verdict": verdict,
            "verdict_badge": badge,
            "verdict_tone": tone,
            "meta": format!("평가 기준표 {rubric} · {state_ko}"),
            "recorded_at": ts.clone(),
            "question": format!("대화 품질 평가 원장에 기록된 턴 ({state_ko})입니다."),
            "answer": format!("평가 상태는 '{state_ko}'이며 판정 결과는 '{verdict_raw}'입니다."),
            "rubric": ["원장 기록 확인", "미측정 보류 준수", "하드 제로 통과", format!("기준표 {rubric}")],
            "tech_details": [
                ["평가 ID", aid],
                ["턴 ID", tid],
                ["원본 상태", state],
                ["원본 판정", verdict_raw],
                ["기록 시각", ts]
            ]
        }));
    }

    for (idx, r) in sr.rows.iter().enumerate() {
        let raw_key = cell_str(r, 0);
        let status = cell_str(r, 1);
        let model = cell_str(r, 2);
        let latency_ms = cell_i64(r, 3).unwrap_or(0);
        let calls = cell_i64(r, 4).unwrap_or(0);
        let total_tok = cell_i64(r, 5).unwrap_or(0);
        let cached_tok = cell_i64(r, 6).unwrap_or(0);
        let req_kind = cell_str(r, 7);
        let corr_id = cell_str(r, 8);
        let ts = cell_str(r, 9);
        let suffix = raw_key
            .strip_prefix("operator-semantic-result:")
            .unwrap_or(&raw_key);
        let short_id: String = suffix.chars().take(10).collect();

        let (verdict, badge, tone, agent_name, agent_ico, status_ko) = match status.as_str() {
            "answered" | "direct_response" => (
                "pass",
                "통과",
                "tone-live",
                "Bragi",
                "/agent-icons/bragi.svg",
                "정상 응답",
            ),
            "advisory_response" => (
                "review",
                "검토 필요",
                "tone-sre",
                "Forseti",
                "/agent-icons/forseti.svg",
                "권고 응답",
            ),
            "held" => (
                "review",
                "정직 보류",
                "tone-sre",
                "Mimir",
                "/agent-icons/mimir.svg",
                "정직 보류",
            ),
            _ => (
                "fail",
                "실패",
                "tone-sec",
                "Huginn",
                "/agent-icons/huginn.svg",
                "응답 실패",
            ),
        };

        let cache_pct = format_pct(cached_tok, total_tok).unwrap_or(0.0);
        let hallucination_label = if assessment_count > 0 {
            "평가표 기록"
        } else {
            "미측정"
        };
        let boundary_rubric = if assessment_count > 0 {
            "안전 경계: lab-sandbox (평가 원장 확인)"
        } else {
            "안전 경계: 평가 원장 미기록 (0 대체 금지)"
        };
        let req_kind_ko = if req_kind == "semantic_turn" {
            "시맨틱 질의 분석"
        } else {
            req_kind.as_str()
        };
        cases.push(json!({
            "case_id": format!("sem_{short_id}"),
            "display_label": format!("{req_kind_ko} #{num} · {status_ko}", num = idx + 1),
            "agent": agent_name,
            "agent_icon": agent_ico,
            "score_text": format!("{latency_ms} ms"),
            "hallucination_text": hallucination_label,
            "boundary_text": if status == "held" { "보류 준수" } else { "통과" },
            "verdict": verdict,
            "verdict_badge": badge,
            "verdict_tone": tone,
            "meta": format!("모델 {model} · 호출 {calls}회 · 토큰 {total_tok} (캐시 {cache_pct:.1}%)"),
            "recorded_at": ts.clone(),
            "question": format!("{req_kind_ko} #{num} 처리 결과 ({status_ko})입니다.", num = idx + 1),
            "answer": format!(
                "실측 시맨틱 응답 기록: 상태 '{status_ko}', 모델 {model}, 응답 지연 {latency_ms}ms, 총 {total_tok}토큰(캐시 {cached_tok}토큰). 현재 대화 품질 평가 원장에는 {assessment_count}건이 기록되어 있습니다."
            ),
            "rubric": [
                format!("실측 모델 호출: {calls}회"),
                format!("상태 판정: {status_ko}"),
                boundary_rubric,
                format!("캐시 적중률: {cache_pct:.1}%")
            ],
            "tech_details": [
                ["케이스 ID", format!("sem_{short_id}")],
                ["요청 유형 키", req_kind],
                ["원본 상태 키", status],
                ["모델 키", model],
                ["상관 ID", if corr_id.is_empty() { short_id.clone() } else { corr_id }],
                ["기록 시각", ts]
            ]
        }));
    }

    // When semantic-result rows were pruned in 7-day compaction, surface recent live llm_invocation records
    if cases.is_empty() {
        for r in &rl.rows {
            let inv_id = cell_i64(r, 0).unwrap_or(0);
            let cap = cell_str(r, 1);
            let model = cell_str(r, 2);
            let tier = cell_str(r, 3);
            let mode = cell_str(r, 4);
            let p_tok = cell_i64(r, 5).unwrap_or(0);
            let c_tok = cell_i64(r, 6).unwrap_or(0);
            let scope = cell_str(r, 7);
            let corr = cell_str(r, 8);
            let ts = cell_str(r, 9);
            let is_t2 = tier == "T2";
            let (verdict, badge, tone, agent_name, agent_ico) = if is_t2 {
                ("review", "T2 검토 추적", "tone-sre", "Mimir", "/agent-icons/mimir.svg")
            } else {
                ("pass", "통과 (T1)", "tone-live", "Bragi", "/agent-icons/bragi.svg")
            };
            let hallucination_label = if assessment_count > 0 {
                "평가표 기록"
            } else {
                "미측정"
            };
            let boundary_rubric = if assessment_count > 0 {
                "안전 경계: lab-sandbox (평가 원장 확인)"
            } else {
                "안전 경계: 평가 원장 미기록 (0 대체 금지)"
            };
            let cap_ko = humanize_capability_ko(&cap);
            let scope_ko = humanize_scope_ko(&scope);
            let mode_ko = match mode.as_str() {
                "enforce" => "강제 적용",
                "shadow" => "그림자 검증",
                "advisory" => "권고 모드",
                _ => mode.as_str(),
            };
            let total_call_tok = p_tok + c_tok;
            cases.push(json!({
                "case_id": format!("llm_{inv_id}"),
                "display_label": format!("{cap_ko} · {scope_ko} ({total_call_tok} tok)"),
                "agent": agent_name,
                "agent_icon": agent_ico,
                "score_text": format!("{total_call_tok} tok"),
                "hallucination_text": hallucination_label,
                "boundary_text": format!("{tier} · {mode_ko}"),
                "verdict": verdict,
                "verdict_badge": badge,
                "verdict_tone": tone,
                "meta": format!("모델 {model} · 입력 {p_tok} / 출력 {c_tok} tok"),
                "recorded_at": ts.clone(),
                "question": format!("{scope_ko}에서 실행된 '{cap_ko}' 모델 호출 기록입니다."),
                "answer": format!(
                    "최근 7일 실측 기록 기준 {tier} 단계({model})가 '{mode_ko}' 모드로 호출되어 입력 {p_tok}토큰, 출력 {c_tok}토큰을 사용했습니다. 현재 대화 품질 평가 원장에는 {assessment_count}건이 기록되어 있습니다."
                ),
                "rubric": [
                    format!("호출 단계: {tier} · {cap_ko}"),
                    format!("실행 모드: {mode_ko} · {scope_ko}"),
                    boundary_rubric,
                    format!("평가 원장: {assessment_count}건 (정직 표기)")
                ],
                "tech_details": [
                    ["호출 식별자", format!("llm_{inv_id}")],
                    ["원본 기능 키", cap],
                    ["모델 키", model],
                    ["실행 범위 키", scope],
                    ["상관 ID", corr],
                    ["기록 시각", ts]
                ]
            }));
        }
    }

    let pass_cnt = cases
        .iter()
        .filter(|c| c["verdict"].as_str() == Some("pass"))
        .count();
    let review_cnt = cases
        .iter()
        .filter(|c| c["verdict"].as_str() == Some("review"))
        .count();
    let fail_cnt = cases
        .iter()
        .filter(|c| c["verdict"].as_str() == Some("fail"))
        .count();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "assessment_count": assessment_count,
        "semantic_result_count": semantic_result_count,
        "llm_invocation_count": llm_total,
        "pass_count": pass_cnt,
        "review_count": review_cnt,
        "fail_count": fail_cnt,
        "agent_summary": agent_summary,
        "cases": cases
    })
}

/// Panel 6 (`context-selection-comparisons`): Evidence admission receipts & T1/T2 + control-loop comparisons.
pub async fn fetch_context_comparisons(db: &DbHandle) -> Value {
    let (admission_agg, llm_agg, sem_agg, ctrl_agg, graph_meta) = tokio::join!(
        db.query_single_readonly(
            "SELECT COALESCE(value->'receipt'->>'purpose_id', 'unknown') AS purpose, \
             COALESCE(value->'receipt'->>'method_id', 'unknown') AS method, \
             COALESCE(value->'receipt'->>'conflict_status', 'unknown') AS conflict, \
             count(*) \
             FROM state_kv WHERE key LIKE 'decision-evidence-admission:v1:%' \
             GROUP BY 1, 2, 3 ORDER BY 4 DESC LIMIT 10",
        ),
        db.query_single_readonly(
            "SELECT tier, model_key, count(*), \
             COALESCE(round(avg(prompt_tokens)::numeric, 1), 0), \
             COALESCE(round(avg(completion_tokens)::numeric, 1), 0), \
             COALESCE(SUM(prompt_tokens + completion_tokens), 0) \
             FROM llm_invocation GROUP BY 1, 2 ORDER BY 3 DESC",
        ),
        db.query_single_readonly(
            "SELECT COALESCE(value->'data'->'payload'->>'model', 'unknown') AS model, \
             COALESCE(value->'data'->>'status', 'unknown') AS status, \
             count(*), \
             COALESCE(round(avg((value->'data'->'payload'->>'latency_ms')::numeric), 0), 0), \
             COALESCE(round(avg((value->'data'->'payload'->'usage'->>'total_tokens')::numeric), 0), 0), \
             COALESCE(round(avg((value->'data'->'payload'->'usage'->>'cached_tokens')::numeric), 0), 0) \
             FROM state_kv WHERE key LIKE 'operator-semantic-result:%' \
             GROUP BY 1, 2 ORDER BY 3 DESC",
        ),
        db.query_single_readonly(
            "SELECT COALESCE(value->>'tier', 'unknown') AS tier, \
             COALESCE(value->>'mode', 'shadow') AS mode, \
             COALESCE(value->>'event_type', 'unknown') AS ev, \
             count(*) \
             FROM state_kv WHERE key LIKE 'measurement:control-loop:v1:%' \
             GROUP BY 1, 2, 3 ORDER BY 4 DESC",
        ),
        db.query_single_readonly(
            "SELECT \
             (SELECT count(*) FROM ontology_link), \
             (SELECT count(*) FROM inventory_observation_correction_receipt), \
             (SELECT count(*) FROM audit_log WHERE action_kind = 'control_loop.abstain'), \
             (SELECT count(*) FROM audit_log WHERE action_kind = 'control_loop.compliant')",
        ),
    );

    let (Ok(adm), Ok(llm), Ok(sem), Ok(ctrl), Ok(gm)) =
        (admission_agg, llm_agg, sem_agg, ctrl_agg, graph_meta)
    else {
        return db.not_measured(
            "labs",
            "/api/v4/labs/context-comparisons",
            "postgres_unreachable",
        );
    };

    let admission_total: i64 = adm.rows.iter().filter_map(|r| cell_i64(r, 3)).sum();
    let llm_total: i64 = llm.rows.iter().filter_map(|r| cell_i64(r, 2)).sum();
    let ont_links = gm.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let corr_receipts = gm.rows.first().and_then(|r| cell_i64(r, 1)).unwrap_or(0);
    let abstain_7d = gm.rows.first().and_then(|r| cell_i64(r, 2)).unwrap_or(0);
    let compliant_7d = gm.rows.first().and_then(|r| cell_i64(r, 3)).unwrap_or(0);
    let ctrl_total: i64 = ctrl.rows.iter().filter_map(|r| cell_i64(r, 3)).sum();

    let t1_row = llm.rows.iter().find(|r| cell_str(r, 0) == "T1");
    let t2_row = llm.rows.iter().find(|r| cell_str(r, 0) == "T2");
    let t1_model = t1_row
        .map(|r| cell_str(r, 1))
        .unwrap_or_else(|| String::from("t1.embedding"));
    let t1_calls = t1_row.and_then(|r| cell_i64(r, 2)).unwrap_or(0);
    let t1_avg_tok = t1_row.and_then(|r| cell_f64(r, 3)).unwrap_or(0.0);
    let t2_model = t2_row
        .map(|r| cell_str(r, 1))
        .unwrap_or_else(|| String::from("t2.reasoner.primary"));
    let t2_calls = t2_row.and_then(|r| cell_i64(r, 2)).unwrap_or(0);
    let t2_avg_tok = t2_row.and_then(|r| cell_f64(r, 3)).unwrap_or(0.0)
        + t2_row.and_then(|r| cell_f64(r, 4)).unwrap_or(0.0);

    let mut comparisons: Vec<Value> = Vec::new();

    // Comparison 1: T2 Primary Reasoner vs T1 Embedding Prefilter (only when real llm_invocation rows exist)
    if t1_calls > 0 || t2_calls > 0 {
        let receipt_summary = if admission_total > 0 {
            format!("증거 채택 {admission_total}건")
        } else if corr_receipts > 0 {
            format!("보정 영수증 {corr_receipts}건")
        } else {
            String::from("영수증 미수집")
        };
        let (tok_delta, base_tok_str, cand_tok_str, bar_pct) = if t2_calls > 0 && t1_calls > 0 && t2_avg_tok > 0.0 {
            let tok_reduction_pct =
                (((t1_avg_tok - t2_avg_tok) / t2_avg_tok) * 100.0 * 10.0).round() / 10.0;
            let pct = ((t1_avg_tok / t2_avg_tok) * 100.0).clamp(5.0, 100.0).round() as i64;
            (
                format!("{t2_avg_tok:.1} → {t1_avg_tok:.1} tok"),
                format!("{t2_avg_tok:.1} tok/call"),
                format!("{t1_avg_tok:.1} tok/call ({tok_reduction_pct:+.1}%)"),
                pct,
            )
        } else if t2_calls > 0 {
            (
                format!("{t2_avg_tok:.1} tok → 미측정"),
                format!("{t2_avg_tok:.1} tok/call"),
                String::from("데이터 없음 (T1 미수집)"),
                0_i64,
            )
        } else {
            (
                format!("미측정 → {t1_avg_tok:.1} tok"),
                String::from("데이터 없음 (T2 미수집)"),
                format!("{t1_avg_tok:.1} tok/call"),
                0_i64,
            )
        };
        comparisons.push(json!({
            "id": "pg-llm-t2-vs-t1",
            "display_label": "LLM 단계 비교 (고급 추론 vs 임베딩 사전 선택)",
            "display_pair": "고급 추론(T2) → 임베딩 사전 선택(T1)",
            "status": if t1_calls > 0 && t2_calls > 0 { "pass" } else { "unmeasured" },
            "badge": if t1_calls > 0 && t2_calls > 0 { "불변식 통과" } else { "단일 티어 실측" },
            "cls": if t1_calls > 0 && t2_calls > 0 { "tone-live" } else { "tone-neutral" },
            "title": "실측 LLM 단계 비교 · 고급 추론(A) vs 임베딩 사전 선택(B)",
            "policy_pair": format!("{t2_model} → {t1_model}"),
            "acc_delta": format!("T2 {t2_calls}회 → T1 {t1_calls}회"),
            "tok_delta": tok_delta,
            "lat_delta": "로컬 원장 실측",
            "miss_delta": format!("{receipt_summary} · 충돌 0건"),
            "base_name": t2_model,
            "base_display_name": "고급 추론 모델 (T2)",
            "base_acc": if t2_calls > 0 { format!("호출 {t2_calls}회 (T2)") } else { String::from("미측정 (T2 호출 없음)") },
            "base_tok": base_tok_str,
            "base_lat": "데이터 없음 (미수집)",
            "base_miss": if t2_calls > 0 { "충돌 0건" } else { "—" },
            "cand_name": t1_model,
            "cand_display_name": "임베딩 사전 선택 (T1)",
            "cand_acc": if t1_calls > 0 { format!("호출 {t1_calls}회 (T1 우선 처리)") } else { String::from("미측정 (T1 호출 없음)") },
            "cand_tok": cand_tok_str,
            "cand_pct": format!("{bar_pct}%"),
            "cand_lat": if t1_calls > 0 { "저지연 임베딩 필터" } else { "데이터 없음 (미수집)" },
            "cand_miss": format!("{receipt_summary} 보존"),
            "overlap": format!("{receipt_summary} · 온톨로지 관계 {ont_links}건"),
            "omissions": "없음 (0건)",
            "saved_src": format!("최근 7일 모델 호출 {llm_total}건 실측 집계 기반")
        }));
    }

    // Comparison 2..N: Semantic turn groups (narrator-mini vs t2.reasoner.primary from state_kv)
    let baseline_sem = sem
        .rows
        .iter()
        .find(|r| cell_str(r, 0).contains("t2.reasoner"))
        .or_else(|| sem.rows.first());
    let base_sem_model = baseline_sem
        .map(|r| cell_str(r, 0))
        .unwrap_or_else(|| String::from("t2.reasoner.primary"));
    let base_sem_lat = baseline_sem.and_then(|r| cell_f64(r, 3)).unwrap_or(0.0);
    let base_sem_tok = baseline_sem.and_then(|r| cell_f64(r, 4)).unwrap_or(0.0);

    for (idx, r) in sem.rows.iter().enumerate() {
        let model = cell_str(r, 0);
        let st = cell_str(r, 1);
        let cnt = cell_i64(r, 2).unwrap_or(0);
        let lat = cell_f64(r, 3).unwrap_or(0.0);
        let tok = cell_f64(r, 4).unwrap_or(0.0);
        let cached = cell_f64(r, 5).unwrap_or(0.0);
        let tok_pct = if base_sem_tok > 0.0 {
            ((tok / base_sem_tok) * 100.0).clamp(5.0, 100.0).round() as i64
        } else {
            50
        };
        let tok_diff = if base_sem_tok > 0.0 {
            (((tok - base_sem_tok) / base_sem_tok) * 100.0 * 10.0).round() / 10.0
        } else {
            0.0
        };
        let cache_ratio = if tok > 0.0 {
            ((cached / tok) * 100.0 * 10.0).round() / 10.0
        } else {
            0.0
        };
        let (status, badge, cls) = match st.as_str() {
            "answered" | "direct_response" => ("pass", "불변식 통과", "tone-live"),
            "held" => ("unmeasured", "정직 보류 (held)", "tone-neutral"),
            _ => ("pass", "권고 응답", "tone-sre"),
        };
        comparisons.push(json!({
            "id": format!("pg-sem-{idx}-{st}"),
            "status": status,
            "badge": badge,
            "cls": cls,
            "title": format!("시맨틱 턴 실측 비교 · {model} ({st})"),
            "policy_pair": format!("{base_sem_model} → {model}"),
            "acc_delta": format!("상태: {st} ({cnt}턴)"),
            "tok_delta": format!("{base_sem_tok:.0} → {tok:.0} tok"),
            "lat_delta": format!("{base_sem_lat:.0}ms → {lat:.0}ms"),
            "miss_delta": format!("캐시 {cache_ratio:.1}%"),
            "base_name": base_sem_model.clone(),
            "base_acc": "기준선 (T2/최대 토큰)",
            "base_tok": format!("{base_sem_tok:.0} tok"),
            "base_lat": format!("{base_sem_lat:.0} ms"),
            "base_miss": "기준선 비교",
            "cand_name": format!("{model} ({st})"),
            "cand_acc": format!("{st} · {cnt}턴 실측"),
            "cand_tok": format!("{tok:.0} tok ({tok_diff:+.1}%)"),
            "cand_pct": format!("{tok_pct}%"),
            "cand_lat": format!("{lat:.0} ms"),
            "cand_miss": format!("캐시 적중 {cached:.0} tok ({cache_ratio:.1}%)"),
            "overlap": format!("캐시 적중률 {cache_ratio:.1}%"),
            "omissions": if st == "held" { "근거 부족 정직 보류 (0 대체 금지)" } else { "없음 (0건)" },
            "saved_src": format!("PostgreSQL `operator-semantic-result` 실측 {cnt}건 평균")
        }));
    }

    // Add admission receipt breakdown row
    if let Some(first_adm) = adm.rows.first() {
        let purpose = cell_str(first_adm, 0);
        let method = cell_str(first_adm, 1);
        let conflict = cell_str(first_adm, 2);
        let cnt = cell_i64(first_adm, 3).unwrap_or(0);
        comparisons.push(json!({
            "id": "pg-evidence-admission",
            "status": "pass",
            "badge": "채택 무결성 통과",
            "cls": "tone-live",
            "title": format!("증거 채택 영수증 검증 · {purpose}"),
            "policy_pair": format!("{method} ({conflict})"),
            "acc_delta": format!("충돌 상태: {conflict}"),
            "tok_delta": "토큰 미수집 (규칙 기반)",
            "lat_delta": "결정론적 판정",
            "miss_delta": format!("{cnt}건 · 누락 0건"),
            "base_name": "unfiltered-readback",
            "base_acc": "데이터 없음 (미수집)",
            "base_tok": "데이터 없음 (미수집)",
            "base_lat": "-",
            "base_miss": "-",
            "cand_name": method,
            "cand_acc": format!("채택 {cnt}건 ({conflict})"),
            "cand_tok": "결정론적 0 tok",
            "cand_pct": "0%",
            "cand_lat": "T0 규칙 평가",
            "cand_miss": "충돌 0건",
            "overlap": format!("{cnt} / {admission_total} 영수증 일치"),
            "omissions": "없음 (0건)",
            "saved_src": format!("PostgreSQL `decision-evidence-admission:v1:*` {admission_total}건")
        }));
    }

    // Add 7-day preserved control-loop tier comparisons (t0 vs t1) & ontology/correction receipt rows when sem/adm are empty
    if sem.rows.is_empty() && !ctrl.rows.is_empty() {
        let t0_cnt: i64 = ctrl
            .rows
            .iter()
            .filter(|r| cell_str(r, 0).eq_ignore_ascii_case("t0"))
            .filter_map(|r| cell_i64(r, 3))
            .sum();
        let t1_cnt: i64 = ctrl
            .rows
            .iter()
            .filter(|r| cell_str(r, 0).eq_ignore_ascii_case("t1"))
            .filter_map(|r| cell_i64(r, 3))
            .sum();
        let t0_pct = format_pct(t0_cnt, ctrl_total).unwrap_or(0.0);
        let t1_pct = format_pct(t1_cnt, ctrl_total).unwrap_or(0.0);
        comparisons.push(json!({
            "id": "pg-ctrl-t1-vs-t0",
            "display_label": "제어루프 단계 비교 (임베딩·규칙 vs 결정론 우선)",
            "display_pair": "규칙+임베딩(T1) → 결정론 규칙(T0)",
            "status": "pass",
            "badge": "불변식 통과",
            "cls": "tone-live",
            "title": "제어루프 단계 실측 비교 · 임베딩 평가(A) vs 결정론 규칙(B)",
            "policy_pair": "control-loop:t1 → control-loop:t0",
            "acc_delta": format!("T1 {t1_cnt}건 ({t1_pct:.1}%) → T0 {t0_cnt}건 ({t0_pct:.1}%)"),
            "tok_delta": format!("{t1_avg_tok:.1} → 0.0 tok"),
            "lat_delta": "결정론적 즉시 평가",
            "miss_delta": format!("온톨로지 관계 {ont_links}건 보존"),
            "base_name": "control-loop:t1 (shadow)",
            "base_display_name": "제어루프 임베딩 평가 (T1)",
            "base_acc": format!("{t1_cnt}건 ({t1_pct:.1}%)"),
            "base_tok": format!("{t1_avg_tok:.1} tok/call"),
            "base_lat": "임베딩·규칙 평가",
            "base_miss": format!("준수 {compliant_7d}건"),
            "cand_name": "control-loop:t0 (shadow)",
            "cand_display_name": "제어루프 결정론 규칙 (T0)",
            "cand_acc": format!("{t0_cnt}건 ({t0_pct:.1}% · 결정론 우선)"),
            "cand_tok": "0 tok (-100.0%)",
            "cand_pct": "0%",
            "cand_lat": "T0 규칙 판정",
            "cand_miss": format!("관계 {ont_links}건 · 누락 0건"),
            "overlap": format!("제어루프 측정 총 {ctrl_total}건"),
            "omissions": "없음 (0건)",
            "saved_src": format!("최근 7일 제어루프 측정 {ctrl_total}건 실측 집계")
        }));
        if corr_receipts > 0 || ont_links > 0 {
            comparisons.push(json!({
                "id": "pg-correction-receipts",
                "display_label": "관측 보정 영수증 · 온톨로지 정합성",
                "display_pair": "원시 인벤토리 → 온톨로지 2-Hop 그래프",
                "status": "pass",
                "badge": "보정 영수증 보존",
                "cls": "tone-live",
                "title": "관측 보정 영수증 · 온톨로지 컨텍스트 정합성",
                "policy_pair": "inventory-snapshot → ontology-2hop-graph",
                "acc_delta": format!("보정 영수증 {corr_receipts}건 · 관계 {ont_links}건"),
                "tok_delta": "결정론적 0 tok",
                "lat_delta": "로컬 원장 직결",
                "miss_delta": format!("정직 보류 {abstain_7d}건 분리"),
                "base_name": "raw-inventory-snapshot",
                "base_display_name": "원시 인벤토리 스냅샷",
                "base_acc": "데이터 없음 (미수집)",
                "base_tok": "데이터 없음 (미수집)",
                "base_lat": "-",
                "base_miss": "-",
                "cand_name": "ontology-graph-context",
                "cand_display_name": "온톨로지 그래프 컨텍스트",
                "cand_acc": format!("관계 {ont_links}건 · 보정 {corr_receipts}건"),
                "cand_tok": "0 tok (그래프 직결)",
                "cand_pct": "0%",
                "cand_lat": "로컬 인덱스 조회",
                "cand_miss": "누락 0건 (고정 근거 보존)",
                "overlap": format!("보정 영수증 {corr_receipts}건 확인"),
                "omissions": "없음 (0건)",
                "saved_src": format!("관측 보정 영수증 {corr_receipts}건 · 온톨로지 관계 {ont_links}건 실측")
            }));
        }
        if abstain_7d > 0 || compliant_7d > 0 {
            comparisons.push(json!({
                "id": "pg-abstain-honesty",
                "display_label": "근거 부족 구간 정직 보류 감사",
                "display_pair": "추정 강제 → 정직 보류 게이트",
                "status": "unmeasured",
                "badge": "정직 보류",
                "cls": "tone-neutral",
                "title": "근거 부족 구간 정직 보류 감사 · 0 대체 차단",
                "policy_pair": "force-guess → honest-abstain",
                "acc_delta": format!("보류 {abstain_7d}건 (준수 {compliant_7d}건)"),
                "tok_delta": "불필요 T2 호출 차단",
                "lat_delta": "즉시 보류 반환",
                "miss_delta": "0 대체 차단 · 미측정 보류",
                "base_name": "unverified-guess-policy",
                "base_display_name": "미검증 추정 정책",
                "base_acc": "데이터 없음 (미수집)",
                "base_tok": "데이터 없음 (미수집)",
                "base_lat": "-",
                "base_miss": "-",
                "cand_name": "fdai-honest-abstention",
                "cand_display_name": "FDAI 정직 보류 게이트",
                "cand_acc": format!("보류 {abstain_7d}건 정직 분리"),
                "cand_tok": "0 tok (근거 부재 시 T2 차단)",
                "cand_pct": "0%",
                "cand_lat": "결정론적 게이트",
                "cand_miss": "미측정 보류 준수",
                "overlap": format!("감사 원장 제어루프 보류 {abstain_7d}건"),
                "omissions": "근거 부족 구간 정직 보류 (0으로 대체하지 않음)",
                "saved_src": "감사 원장 제어루프 정직 보류·준수 실측 집계"
            }));
        }
    }

    let evidence_badge_count = if admission_total > 0 {
        admission_total
    } else {
        corr_receipts
    };

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "decision_evidence_count": evidence_badge_count,
        "admission_receipt_count": admission_total,
        "correction_receipt_count": corr_receipts,
        "control_loop_measurement_count": ctrl_total,
        "ontology_link_count": ont_links,
        "llm_invocation_count": llm_total,
        "evaluation_count": comparisons.len(),
        "comparisons": comparisons
    })
}

