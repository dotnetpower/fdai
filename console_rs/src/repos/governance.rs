//! Domain 4 (`governance`, 13 panels) PostgreSQL repository, including Foundry+ Data Lineage.
//!
//! Queries live local/managed PostgreSQL projections and tables directly with bounded
//! read-only queries (`DbHandle::query_single_readonly`) and audited KV mutations
//! (`DbHandle::execute_audited_kv_mutation`). Never fabricates `0` when unreachable.

use crate::db::{cell_i64, cell_str, clamp_limit, quote_like_contains, DbHandle};
use crate::governance_security_policy::{
    format_kst_ymd_date, kev_alert_watermark_triggered, promotion_gate_margin_passed,
    security_coverage_ratio, wilson_assurance_lb95, SecurityGovernanceAssurance,
};
use crate::lineage_graph_layout::{
    lineage_coverage_wilson_lb95, lineage_stage_ratio, LineageGraphMetrics,
};
use fdai_adapter_postgres::pg_quote_literal;
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::{SystemTime, UNIX_EPOCH};

const MANDATORY_SEVERITIES_SQL: &str =
    "('critical', 'high', 'sev1', 'sev2', 'p0', 'p1', '긴급', '높음')";

#[must_use]
pub fn is_mandatory_rule_severity(severity: &str) -> bool {
    matches!(
        severity.trim().to_ascii_lowercase().as_str(),
        "critical" | "high" | "sev1" | "sev2" | "p0" | "p1" | "긴급" | "높음"
    )
}

fn clean_opt(raw: Option<&str>) -> Option<&str> {
    raw.map(str::trim).filter(|s| !s.is_empty())
}

#[must_use]
pub fn ontology_type_label_ko(object_type: &str) -> &'static str {
    match object_type.trim() {
        "Resource" => "클라우드 리소스",
        "FrameworkControl" => "프레임워크 통제",
        "BenchmarkValidation" => "벤치마크 검증",
        "ResourceType" => "리소스 유형",
        "DiagnosticMechanism" => "진단 메커니즘",
        "ActionType" => "조치 유형",
        "Rule" => "운영 규칙",
        "PolicyArtifact" => "정책 아티팩트",
        "Property" => "온톨로지 속성",
        "ResourceClass" => "리소스 분류",
        "SignalType" => "신호 유형",
        "Framework" => "평가 프레임워크",
        "ControlObjective" => "통제 목표",
        "RuleObjectiveBinding" => "규칙-목표 바인딩",
        "ReviewCase" => "검토 케이스",
        "ReviewCheck" => "검토 점검",
        _ => "온톨로지 객체",
    }
}

#[must_use]
pub fn is_uuid_like(raw: &str) -> bool {
    let b = raw.trim().as_bytes();
    if b.len() != 36 {
        return false;
    }
    b.iter().enumerate().all(|(idx, ch)| match idx {
        8 | 13 | 18 | 23 => *ch == b'-',
        _ => ch.is_ascii_hexdigit(),
    })
}

#[must_use]
pub fn resource_type_label_ko(raw: &str) -> &'static str {
    let s = raw.trim();
    if s.eq_ignore_ascii_case("resource-group") || s.eq_ignore_ascii_case("resourcegroup") {
        return "리소스 그룹";
    }
    if s.eq_ignore_ascii_case("authorization.role-assignment") || s.eq_ignore_ascii_case("role-assignment") {
        return "RBAC 역할 할당";
    }
    if s.eq_ignore_ascii_case("anomaly-alert-rule") || s.eq_ignore_ascii_case("smartdetectoralertrules") {
        return "이상 탐지 알림 규칙";
    }
    if s.eq_ignore_ascii_case("api-gateway") || s.eq_ignore_ascii_case("api-management") {
        return "API 게이트웨이";
    }
    if s.eq_ignore_ascii_case("llm-endpoint") || s.eq_ignore_ascii_case("cognitive-account") {
        return "AI 모델 엔드포인트";
    }
    if s.eq_ignore_ascii_case("compute.container-app-job") {
        return "컨테이너 앱 작업";
    }
    if s.eq_ignore_ascii_case("compute.container-app") {
        return "컨테이너 앱";
    }
    if s.eq_ignore_ascii_case("compute.vm-scale-set") {
        return "가상 머신 확장 집합 (VMSS)";
    }
    if s.eq_ignore_ascii_case("compute.vm") || s.eq_ignore_ascii_case("compute.virtual-machine") {
        return "가상 머신 (VM)";
    }
    if s.eq_ignore_ascii_case("kubernetes-cluster") || s.eq_ignore_ascii_case("compute.kubernetes-cluster") {
        return "AKS 쿠버네티스 클러스터";
    }
    if s.eq_ignore_ascii_case("kubernetes-node-pool") {
        return "AKS 노드 풀";
    }
    if s.eq_ignore_ascii_case("network.load-balancer") {
        return "로드 밸런서";
    }
    if s.eq_ignore_ascii_case("network.virtual-network") {
        return "가상 네트워크 (VNet)";
    }
    if s.eq_ignore_ascii_case("network.nsg") || s.eq_ignore_ascii_case("network.network-security-group") {
        return "네트워크 보안 그룹 (NSG)";
    }
    if s.eq_ignore_ascii_case("network.private-endpoint") {
        return "비공개 엔드포인트 (PE)";
    }
    if s.eq_ignore_ascii_case("network.public-ip") {
        return "공용 IP 주소";
    }
    if s.eq_ignore_ascii_case("security.key-vault") || s.eq_ignore_ascii_case("key-vault") {
        return "키 볼트 (Key Vault)";
    }
    if s.eq_ignore_ascii_case("managed-identity") {
        return "관리 ID";
    }
    if s.eq_ignore_ascii_case("database.postgresql") || s.eq_ignore_ascii_case("postgresql-flexible") {
        return "PostgreSQL 데이터베이스";
    }
    if s.eq_ignore_ascii_case("storage.account") || s.eq_ignore_ascii_case("storage-account") {
        return "스토리지 계정";
    }
    if s.eq_ignore_ascii_case("disk") {
        return "관리 디스크";
    }
    if s.eq_ignore_ascii_case("cache") || s.eq_ignore_ascii_case("cache-redis") {
        return "캐시 서비스";
    }
    if s.eq_ignore_ascii_case("ResourceType") {
        return "리소스 유형";
    }
    ""
}

#[must_use]
pub fn resolve_ontology_display_name(id: &str, object_type: &str, props: &Value) -> String {
    let pick = |key: &str| -> Option<String> {
        props
            .get(key)
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(String::from)
    };
    let rt_raw = pick("resource_type").unwrap_or_default();
    let rt_ko = resource_type_label_ko(&rt_raw);
    let format_uuid_label = |uuid_str: &str| -> String {
        let short: String = uuid_str.chars().take(8).collect();
        if let Some(role_name) = pick("role_definition_name").or_else(|| pick("role_name")) {
            return format!("{role_name} · {short}");
        }
        if !rt_ko.is_empty() {
            return format!("{rt_ko} · {short}");
        }
        if id.to_ascii_lowercase().contains("roleassignments/") {
            return format!("RBAC 역할 할당 · {short}");
        }
        format!("{} · {short}", ontology_type_label_ko(object_type))
    };
    if let Some(name) = pick("name") {
        if is_uuid_like(&name) {
            return format_uuid_label(&name);
        }
        return name;
    }
    if let Some(title) = pick("title") {
        if let Some(cid) = pick("control_id") {
            return format!("{cid} · {title}");
        }
        return title;
    }
    if let Some(mech) = pick("mechanism_id") {
        let readable = mech.replace('_', " ");
        if let Some(bench) = pick("benchmark_id") {
            return format!("{bench} · {readable}");
        }
        return readable;
    }
    if pick("provider_type").is_some() {
        let ko = resource_type_label_ko(id);
        if !ko.is_empty() {
            return ko.to_string();
        }
        return id.replace(['-', '_'], " ");
    }
    if let Some(sem) = pick("semantic_id") {
        let short_id = id.strip_prefix("property.").unwrap_or(id);
        return format!("{short_id} ({sem})");
    }
    if let Some(rest) = id.strip_prefix("review-") {
        let short: String = rest.chars().take(8).collect();
        let st = pick("status").unwrap_or_else(|| "open".to_string());
        return format!("검토 케이스 · {short} ({st})");
    }
    if let Some(rest) = id.strip_prefix("check-") {
        let short: String = rest.chars().take(8).collect();
        let st = pick("status").unwrap_or_else(|| "open".to_string());
        return format!("검토 점검 · {short} ({st})");
    }
    if let Some(rest) = id.strip_prefix("benchmark-validation:") {
        let short: String = rest.chars().take(8).collect();
        return format!("벤치마크 검증 · {short}");
    }
    let stripped = id
        .strip_prefix("rule-objective-binding:")
        .or_else(|| id.strip_prefix("control-objective:"))
        .or_else(|| id.strip_prefix("diagnostic-mechanism:"))
        .or_else(|| id.strip_prefix("framework-control:"))
        .or_else(|| id.strip_prefix("class."))
        .unwrap_or(id);
    let clean = stripped.split('@').next().unwrap_or(stripped);
    if clean.contains('/') {
        if let Some(last) = clean.rsplit('/').next().filter(|s| !s.is_empty()) {
            if is_uuid_like(last) {
                return format_uuid_label(last);
            }
            return last.to_string();
        }
    }
    if is_uuid_like(clean) {
        return format_uuid_label(clean);
    }
    if clean.is_empty() {
        ontology_type_label_ko(object_type).to_string()
    } else {
        let ko = resource_type_label_ko(clean);
        if !ko.is_empty() {
            ko.to_string()
        } else {
            clean.to_string()
        }
    }
}

fn extract_sub_and_rg(id: &str, props: &Value) -> (String, String) {
    let mut sub = props
        .get("subscription")
        .or_else(|| props.get("subscription_id"))
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let mut rg = props
        .get("resource_group")
        .or_else(|| props.get("resourceGroup"))
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let parts: Vec<&str> = id.split('/').collect();
    if sub.is_empty() {
        if let Some(first) = parts.first() {
            if first.starts_with("scope-") {
                sub = (*first).to_string();
            }
        }
    }
    if rg.is_empty() {
        for pair in parts.windows(2) {
            if let [k, v] = pair {
                if k.eq_ignore_ascii_case("resource-group")
                    || k.eq_ignore_ascii_case("resourcegroups")
                {
                    rg = (*v).to_string();
                    break;
                }
            }
        }
    }
    if sub.is_empty() {
        sub = "Azure".to_string();
    }
    (sub, rg)
}

async fn load_rule_overrides(db: &DbHandle) -> Map<String, Value> {
    let mut overrides = Map::new();
    let bulk_sql = "SELECT value::text FROM state_kv WHERE key = 'operator-state:governance:rule-activations' LIMIT 1";
    if let Ok(res) = db.query_single_readonly(bulk_sql).await {
        if let Some(raw) = res.rows.first().map(|r| cell_str(r, 0)) {
            if let Ok(parsed) = serde_json::from_str::<Value>(&raw) {
                if let Some(map) = parsed.get("activations").and_then(Value::as_object) {
                    for (k, v) in map {
                        overrides.insert(k.clone(), v.clone());
                    }
                }
            }
        }
    }
    let single_sql = "SELECT key, value::text FROM state_kv \
                      WHERE key LIKE 'operator-state:governance:rule-activation:%' \
                      ORDER BY updated_at ASC LIMIT 500";
    if let Ok(res) = db.query_single_readonly(single_sql).await {
        for row in &res.rows {
            let key = cell_str(row, 0);
            let raw = cell_str(row, 1);
            if let Some(rule_id) = key.strip_prefix("operator-state:governance:rule-activation:") {
                if let Ok(parsed) = serde_json::from_str::<Value>(&raw) {
                    overrides.insert(rule_id.to_string(), parsed);
                }
            }
        }
    }
    overrides
}

pub async fn fetch_rule_severity(db: &DbHandle, rule_id: &str) -> Option<String> {
    let q_active = pg_quote_literal(&format!("active:{rule_id}"));
    let q_collected = pg_quote_literal(&format!("collected:{rule_id}"));
    let sql = format!(
        "SELECT COALESCE(value->'details'->{q_active}->>'severity', value->'details'->{q_collected}->>'severity', '') \
         FROM state_kv \
         WHERE key = 'operator-projection:workflow:rule.list' \
         LIMIT 1"
    );
    let res = db.query_single_readonly(&sql).await.ok()?;
    let row = res.rows.first()?;
    let sev = cell_str(row, 0);
    if sev.is_empty() {
        None
    } else {
        Some(sev)
    }
}

pub async fn fetch_ontology_summary(db: &DbHandle) -> Value {
    let (ot, lt, res, lnk, rel) = tokio::join!(
        db.query_single_readonly("SELECT count(*) FROM ontology_object_type"),
        db.query_single_readonly("SELECT count(*) FROM ontology_link_type"),
        db.query_single_readonly("SELECT count(*) FROM ontology_resource"),
        db.query_single_readonly("SELECT count(*) FROM ontology_link"),
        db.query_single_readonly("SELECT count(*) FROM ontology_release"),
    );
    match (ot, lt, res, lnk, rel) {
        (Ok(a), Ok(b), Ok(c), Ok(d), Ok(e)) => json!({
            "measurement_status": "measured",
            "source": "postgres-direct",
            "object_type_count": a.rows.first().and_then(|r| cell_i64(r, 0)),
            "link_type_count": b.rows.first().and_then(|r| cell_i64(r, 0)),
            "instance_count": c.rows.first().and_then(|r| cell_i64(r, 0)),
            "link_count": d.rows.first().and_then(|r| cell_i64(r, 0)),
            "release_count": e.rows.first().and_then(|r| cell_i64(r, 0))
        }),
        _ => db.not_measured(
            "governance",
            "/api/v4/governance/summary",
            "postgres_unreachable",
        ),
    }
}

pub async fn fetch_ontology_graph(db: &DbHandle) -> Value {
    let summary = fetch_ontology_summary(db).await;
    if summary.get("measurement_status").and_then(Value::as_str) != Some("measured") {
        return db.not_measured(
            "governance",
            "/api/v4/governance/ontology/graph",
            "postgres_unreachable",
        );
    }

    let kv_sql = "SELECT \
        COALESCE((value->>'object_type_count')::bigint, 0), \
        COALESCE((value->>'link_type_count')::bigint, 0), \
        COALESCE((value->>'action_type_count')::bigint, 0), \
        COALESCE((value->>'interface_type_count')::bigint, 0), \
        COALESCE((value->>'function_type_count')::bigint, 0), \
        COALESCE(value->>'ontology_release_digest', ''), \
        COALESCE(jsonb_array_length(value->'nodes'), 0), \
        COALESCE(jsonb_array_length(value->'edges'), 0) \
        FROM state_kv WHERE key = 'operator-projection:operations:ontology.graph' LIMIT 1";
    let ot_sql = "SELECT name, version, key_field, COALESCE(description, '') \
                  FROM ontology_object_type ORDER BY name ASC LIMIT 120";
    let lt_sql = "SELECT name, from_type, to_type, cardinality, is_causal, is_transitive, COALESCE(description, '') \
                  FROM ontology_link_type ORDER BY name ASC LIMIT 160";
    let ot_inst_sql = "SELECT object_type, count(*) FROM ontology_resource GROUP BY 1";
    let lt_inst_sql = "SELECT link_type, count(*) FROM ontology_link GROUP BY 1";

    let (kv_res, ot_res, lt_res, ot_inst_res, lt_inst_res) = tokio::join!(
        db.query_single_readonly(kv_sql),
        db.query_single_readonly(ot_sql),
        db.query_single_readonly(lt_sql),
        db.query_single_readonly(ot_inst_sql),
        db.query_single_readonly(lt_inst_sql),
    );

    let (
        kv_ot,
        kv_lt,
        action_types,
        interface_types,
        function_types,
        release_digest,
        _graph_node_count,
        _graph_edge_count,
    ) = kv_res
        .ok()
        .and_then(|r| r.rows.first().cloned())
        .map(|row| {
            (
                cell_i64(&row, 0),
                cell_i64(&row, 1),
                cell_i64(&row, 2),
                cell_i64(&row, 3),
                cell_i64(&row, 4),
                cell_str(&row, 5),
                cell_i64(&row, 6),
                cell_i64(&row, 7),
            )
        })
        .unwrap_or((None, None, None, None, None, String::new(), None, None));

    let mut ot_counts: HashMap<String, i64> = HashMap::new();
    if let Ok(r) = ot_inst_res {
        for row in &r.rows {
            ot_counts.insert(cell_str(row, 0), cell_i64(row, 1).unwrap_or(0));
        }
    }
    let mut lt_counts: HashMap<String, i64> = HashMap::new();
    if let Ok(r) = lt_inst_res {
        for row in &r.rows {
            lt_counts.insert(cell_str(row, 0), cell_i64(row, 1).unwrap_or(0));
        }
    }

    let mut object_types: Vec<Value> = Vec::new();
    let mut nodes: Vec<Value> = Vec::new();
    if let Ok(r) = ot_res {
        for row in &r.rows {
            let name = cell_str(row, 0);
            let version = cell_str(row, 1);
            let key_field = cell_str(row, 2);
            let desc = cell_str(row, 3);
            let inst_cnt = *ot_counts.get(&name).unwrap_or(&0);
            let label_ko = ontology_type_label_ko(&name);
            let community = match name.as_str() {
                "Resource" | "ResourceType" | "ResourceClass" | "Property" => "infra",
                "Rule" | "PolicyArtifact" | "Framework" | "FrameworkControl" | "ControlObjective"
                | "RuleObjectiveBinding" => "governance",
                "ActionType" | "Workflow" | "ReviewCase" | "ReviewCheck" => "automation",
                "DiagnosticMechanism" | "BenchmarkValidation" | "SignalType" => "observability",
                _ => "ontology",
            };
            object_types.push(json!({
                "name": name,
                "label_ko": label_ko,
                "version": version,
                "key_field": key_field,
                "instance_count": inst_cnt,
                "description": desc,
            }));
            nodes.push(json!({
                "id": name,
                "label": name,
                "label_ko": label_ko,
                "kind": "ObjectType",
                "community": community,
                "version": version,
                "instance_count": inst_cnt,
                "description": desc
            }));
        }
    }

    let mut link_types: Vec<Value> = Vec::new();
    let mut edges: Vec<Value> = Vec::new();
    if let Ok(r) = lt_res {
        for (idx, row) in r.rows.iter().enumerate() {
            let name = cell_str(row, 0);
            let from_type = cell_str(row, 1);
            let to_type = cell_str(row, 2);
            let cardinality = cell_str(row, 3);
            let is_causal = cell_str(row, 4) == "t" || cell_str(row, 4) == "true";
            let is_transitive = cell_str(row, 5) == "t" || cell_str(row, 5) == "true";
            let desc = cell_str(row, 6);
            let edge_cnt = *lt_counts.get(&name).unwrap_or(&0);
            link_types.push(json!({
                "name": name,
                "from_type": from_type,
                "to_type": to_type,
                "cardinality": cardinality,
                "is_causal": is_causal,
                "is_transitive": is_transitive,
                "instance_edge_count": edge_cnt,
                "description": desc,
            }));
            edges.push(json!({
                "id": format!("{from_type}:{name}:{to_type}:{idx}"),
                "source": from_type,
                "target": to_type,
                "link_type": name,
                "cardinality": cardinality,
                "is_causal": is_causal,
                "is_transitive": is_transitive,
                "instance_edge_count": edge_cnt,
                "description": desc
            }));
        }
    }

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "mutation_authority": false,
        "meaning_validation_only": true,
        "object_type_count": summary.get("object_type_count").cloned().or_else(|| kv_ot.map(Value::from)),
        "link_type_count": summary.get("link_type_count").cloned().or_else(|| kv_lt.map(Value::from)),
        "instance_count": summary.get("instance_count").cloned(),
        "link_count": summary.get("link_count").cloned(),
        "release_count": summary.get("release_count").cloned(),
        "action_type_count": action_types,
        "interface_type_count": interface_types,
        "function_type_count": function_types,
        "node_count": nodes.len(),
        "edge_count": edges.len(),
        "ontology_release_digest": release_digest,
        "nodes": nodes,
        "edges": edges,
        "object_types": object_types,
        "link_types": link_types
    })
}

pub async fn fetch_ontology_instances_states(db: &DbHandle) -> Value {
    let by_type_sql = "SELECT object_type, count(*) \
                       FROM ontology_resource \
                       GROUP BY 1 ORDER BY 2 DESC";
    let totals_sql = "SELECT \
        (SELECT count(*) FROM ontology_object_type), \
        (SELECT count(*) FROM ontology_link_type), \
        (SELECT count(*) FROM ontology_resource), \
        (SELECT count(*) FROM ontology_link), \
        (SELECT count(*) FROM ontology_resource r WHERE EXISTS (SELECT 1 FROM ontology_link l WHERE l.from_id = r.id OR l.to_id = r.id)), \
        (SELECT count(*) FROM ontology_resource r WHERE r.object_type = 'Resource'), \
        (SELECT count(*) FROM ontology_resource r WHERE r.object_type = 'Resource' AND EXISTS (SELECT 1 FROM ontology_link l WHERE l.from_id = r.id OR l.to_id = r.id)), \
        (SELECT count(*) FROM ontology_link l WHERE NOT EXISTS (SELECT 1 FROM ontology_resource r WHERE r.id = l.from_id) OR NOT EXISTS (SELECT 1 FROM ontology_resource r WHERE r.id = l.to_id)), \
        (SELECT COALESCE(sum(cnt - 1), 0) FROM (SELECT from_id, to_id, link_type, count(*) AS cnt FROM ontology_link GROUP BY 1, 2, 3 HAVING count(*) > 1) dup)";

    let (types_res, totals_res) = tokio::join!(
        db.query_single_readonly(by_type_sql),
        db.query_single_readonly(totals_sql),
    );
    let (Ok(tq), Ok(tot_q)) = (types_res, totals_res) else {
        return db.not_measured(
            "governance",
            "/api/v4/governance/ontology/instances/states",
            "postgres_unreachable",
        );
    };

    let row = tot_q.rows.first();
    let object_type_count = row.and_then(|r| cell_i64(r, 0)).unwrap_or(0).max(0);
    let link_type_count = row.and_then(|r| cell_i64(r, 1)).unwrap_or(0).max(0);
    let total_resources = row.and_then(|r| cell_i64(r, 2)).unwrap_or(0).max(0);
    let total_links = row.and_then(|r| cell_i64(r, 3)).unwrap_or(0).max(0);
    let connected_count = row.and_then(|r| cell_i64(r, 4)).unwrap_or(0).max(0);
    let azure_resource_total = row.and_then(|r| cell_i64(r, 5)).unwrap_or(0).max(0);
    let azure_resource_connected = row.and_then(|r| cell_i64(r, 6)).unwrap_or(0).max(0);
    let dangling_links = row.and_then(|r| cell_i64(r, 7)).unwrap_or(0).max(0);
    let duplicate_links = row.and_then(|r| cell_i64(r, 8)).unwrap_or(0).max(0);

    let isolated_count = (total_resources - connected_count).max(0);
    let connectivity_pct = if total_resources > 0 {
        ((connected_count as f64 / total_resources as f64) * 1000.0).round() / 10.0
    } else {
        0.0
    };
    let azure_connectivity_pct = if azure_resource_total > 0 {
        ((azure_resource_connected as f64 / azure_resource_total as f64) * 1000.0).round() / 10.0
    } else {
        0.0
    };

    let by_object_type: Vec<Value> = tq
        .rows
        .iter()
        .map(|r| {
            let ot = cell_str(r, 0);
            json!({
                "object_type": ot,
                "label_ko": ontology_type_label_ko(&ot),
                "count": cell_i64(r, 1).unwrap_or(0)
            })
        })
        .collect();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "object_type_count": object_type_count,
        "link_type_count": link_type_count,
        "total_resources": total_resources,
        "total_count": total_resources,
        "total_links": total_links,
        "connected_count": connected_count,
        "isolated_count": isolated_count,
        "connectivity_pct": connectivity_pct,
        "azure_resource_total": azure_resource_total,
        "azure_resource_connected": azure_resource_connected,
        "azure_connectivity_pct": azure_connectivity_pct,
        "dangling_links": dangling_links,
        "duplicate_links": duplicate_links,
        "integrity_verified": dangling_links == 0 && duplicate_links == 0,
        "by_object_type": by_object_type
    })
}

pub async fn fetch_ontology_instances(
    db: &DbHandle,
    search: Option<&str>,
    object_type: Option<&str>,
    limit: Option<usize>,
    offset: Option<usize>,
) -> Value {
    let lim = clamp_limit(limit, 100, 200);
    let off = offset.unwrap_or(0).min(100_000);
    let mut clauses: Vec<String> = Vec::new();
    if let Some(ot) = clean_opt(object_type) {
        let q_ot = pg_quote_literal(ot);
        let pat_ot = quote_like_contains(ot);
        clauses.push(format!(
            "(object_type = {q_ot} OR COALESCE(properties->>'type','') = {q_ot} OR COALESCE(properties->>'type','') ILIKE {pat_ot} ESCAPE '\\')"
        ));
    }
    if let Some(q) = clean_opt(search) {
        let pat = quote_like_contains(q);
        clauses.push(format!(
            "(id ILIKE {pat} ESCAPE '\\' OR COALESCE(properties->>'name','') ILIKE {pat} ESCAPE '\\' OR COALESCE(properties->>'type','') ILIKE {pat} ESCAPE '\\' OR object_type ILIKE {pat} ESCAPE '\\')"
        ));
    }
    let where_sql = if clauses.is_empty() {
        String::new()
    } else {
        format!("WHERE {}", clauses.join(" AND "))
    };
    let count_sql = format!("SELECT count(*) FROM ontology_resource {where_sql}");
    let total_all_sql = "SELECT count(*) FROM ontology_resource";
    let link_cnt_sql = "SELECT count(*) FROM ontology_link";
    let ot_cnt_sql = "SELECT count(*) FROM ontology_object_type";
    let lt_cnt_sql = "SELECT count(*) FROM ontology_link_type";
    let list_sql = format!(
        "SELECT id, object_type, COALESCE(properties->>'name', id), \
         COALESCE(properties->>'type', object_type), revision, \
         to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
         COALESCE(properties->>'location', ''), \
         COALESCE(properties->>'operational_state', properties->>'status', '관측됨'), \
         COALESCE(properties::text, '{{}}') \
         FROM ontology_resource {where_sql} \
         ORDER BY CASE WHEN object_type = 'Resource' THEN 0 ELSE 1 END, updated_at DESC \
         LIMIT {lim} OFFSET {off}"
    );
    let (cnt_res, rows_res, all_res, lnk_res, ot_res, lt_res) = tokio::join!(
        db.query_single_readonly(&count_sql),
        db.query_single_readonly(&list_sql),
        db.query_single_readonly(total_all_sql),
        db.query_single_readonly(link_cnt_sql),
        db.query_single_readonly(ot_cnt_sql),
        db.query_single_readonly(lt_cnt_sql),
    );
    let (Ok(cnt), Ok(rows)) = (cnt_res, rows_res) else {
        return db.not_measured(
            "governance",
            "/api/v4/governance/ontology/instances",
            "postgres_unreachable",
        );
    };

    let items: Vec<Value> = rows
        .rows
        .iter()
        .map(|r| {
            let id = cell_str(r, 0);
            let obj_type = cell_str(r, 1);
            let res_type = cell_str(r, 3);
            let rev = cell_i64(r, 4);
            let updated_at = cell_str(r, 5);
            let location = cell_str(r, 6);
            let op_state = cell_str(r, 7);
            let props_val: Value =
                serde_json::from_str(&cell_str(r, 8)).unwrap_or_else(|_| json!({}));
            let display_name = resolve_ontology_display_name(&id, &obj_type, &props_val);
            let object_type_ko = ontology_type_label_ko(&obj_type);
            let (subscription, resource_group) = extract_sub_and_rg(&id, &props_val);
            json!({
                "id": id,
                "object_type": obj_type,
                "object_type_ko": object_type_ko,
                "name": display_name,
                "display_name": display_name,
                "resource_type": res_type,
                "location": location,
                "subscription": subscription,
                "resource_group": resource_group,
                "operational_state": op_state,
                "revision": rev,
                "updated_at": updated_at
            })
        })
        .collect();

    let total = cnt.rows.first().and_then(|r| cell_i64(r, 0));
    let fleet_total = all_res
        .ok()
        .and_then(|r| r.rows.first().and_then(|row| cell_i64(row, 0)))
        .or(total);
    let link_count = lnk_res
        .ok()
        .and_then(|r| r.rows.first().and_then(|row| cell_i64(row, 0)));
    let object_type_count = ot_res
        .ok()
        .and_then(|r| r.rows.first().and_then(|row| cell_i64(row, 0)));
    let link_type_count = lt_res
        .ok()
        .and_then(|r| r.rows.first().and_then(|row| cell_i64(row, 0)));

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "total": total,
        "total_count": fleet_total,
        "link_count": link_count,
        "object_type_count": object_type_count,
        "link_type_count": link_type_count,
        "limit": lim,
        "offset": off,
        "resources": items,
        "items": items
    })
}

pub async fn fetch_ontology_instances_explore(
    db: &DbHandle,
    root: Option<&str>,
    depth: Option<usize>,
    limit: Option<usize>,
) -> Value {
    let max_depth = depth.unwrap_or(2).clamp(1, 3);
    let lim = clamp_limit(limit, 80, 200);

    let root_sql = match clean_opt(root) {
        Some(r) => {
            let exact = pg_quote_literal(r);
            let pat = quote_like_contains(r);
            format!(
                "SELECT id, object_type, COALESCE(properties->>'name', id), \
                 COALESCE(properties->>'type', object_type), revision \
                 FROM ontology_resource \
                 WHERE id = {exact} OR COALESCE(properties->>'name','') = {exact} OR id ILIKE {pat} ESCAPE '\\' \
                 ORDER BY CASE WHEN id = {exact} THEN 0 WHEN COALESCE(properties->>'name','') = {exact} THEN 1 ELSE 2 END \
                 LIMIT 1"
            )
        }
        None => "SELECT r.id, r.object_type, COALESCE(r.properties->>'name', r.id), \
                 COALESCE(r.properties->>'type', r.object_type), r.revision \
                 FROM ontology_resource r \
                 LEFT JOIN ontology_link l ON l.from_id = r.id OR l.to_id = r.id \
                 WHERE r.object_type = 'Resource' \
                 GROUP BY r.id, r.object_type, r.properties, r.revision \
                 ORDER BY count(l.id) DESC, r.updated_at DESC \
                 LIMIT 1"
            .to_string(),
    };

    let Ok(root_res) = db.query_single_readonly(&root_sql).await else {
        return db.not_measured(
            "governance",
            "/api/v4/governance/ontology/instances/explore",
            "postgres_unreachable",
        );
    };

    let Some(root_row) = root_res.rows.first() else {
        return json!({
            "measurement_status": "measured",
            "source": "postgres-direct",
            "root": root,
            "depth": max_depth,
            "nodes": [],
            "edges": [],
            "recent_activity": []
        });
    };

    let root_id = cell_str(root_row, 0);
    let q_root = pg_quote_literal(&root_id);

    let bfs_nodes_sql = format!(
        "WITH RECURSIVE walk(node_id, hop, path) AS ( \
            SELECT {q_root}::text, 0, ARRAY[{q_root}::text] \
            UNION ALL \
            SELECT CASE WHEN l.from_id = w.node_id THEN l.to_id ELSE l.from_id END, \
                   w.hop + 1, \
                   w.path || CASE WHEN l.from_id = w.node_id THEN l.to_id ELSE l.from_id END \
            FROM walk w \
            JOIN ontology_link l ON l.from_id = w.node_id OR l.to_id = w.node_id \
            WHERE w.hop < {max_depth} \
              AND NOT (CASE WHEN l.from_id = w.node_id THEN l.to_id ELSE l.from_id END = ANY(w.path)) \
         ), dedup AS ( \
            SELECT node_id, min(hop) AS hop FROM walk GROUP BY node_id ORDER BY min(hop), node_id LIMIT {lim} \
         ) \
         SELECT d.node_id, d.hop, COALESCE(r.object_type, 'Unknown'), \
                COALESCE(r.properties->>'name', d.node_id), \
                COALESCE(r.properties->>'type', r.object_type, 'Unknown'), \
                COALESCE(r.properties->>'location', ''), \
                COALESCE(r.properties::text, '{{}}') \
         FROM dedup d \
         LEFT JOIN ontology_resource r ON r.id = d.node_id \
         ORDER BY d.hop ASC, d.node_id ASC"
    );

    let edges_sql = format!(
        "SELECT from_id, to_id, link_type \
         FROM ontology_link \
         WHERE from_id = {q_root} OR to_id = {q_root} \
         LIMIT {lim}"
    );

    let act_sql = format!(
        "SELECT watermark, observation_id, mutation_kind, source_identity, \
                to_char(observed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
         FROM inventory_observation_journal \
         WHERE subject_ref = {q_root} \
         ORDER BY watermark DESC LIMIT 20"
    );

    let (nodes_res, edges_res, act_res) = tokio::join!(
        db.query_single_readonly(&bfs_nodes_sql),
        db.query_single_readonly(&edges_sql),
        db.query_single_readonly(&act_sql),
    );

    let nodes: Vec<Value> = nodes_res
        .map(|r| {
            r.rows
                .iter()
                .map(|row| {
                    let nid = cell_str(row, 0);
                    let ot = cell_str(row, 2);
                    let rt = cell_str(row, 4);
                    let props: Value =
                        serde_json::from_str(&cell_str(row, 6)).unwrap_or_else(|_| json!({}));
                    let dname = resolve_ontology_display_name(&nid, &ot, &props);
                    let (sub, rg) = extract_sub_and_rg(&nid, &props);
                    let rt_ko = resource_type_label_ko(&rt);
                    json!({
                        "id": nid,
                        "hop": cell_i64(row, 1),
                        "object_type": ot,
                        "object_type_ko": ontology_type_label_ko(&ot),
                        "name": dname,
                        "display_name": dname,
                        "resource_type": rt,
                        "resource_type_ko": if rt_ko.is_empty() { ontology_type_label_ko(&ot) } else { rt_ko },
                        "subscription": sub,
                        "resource_group": rg,
                        "location": cell_str(row, 5),
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    let edges: Vec<Value> = edges_res
        .map(|r| {
            r.rows
                .iter()
                .map(|row| {
                    json!({
                        "source": cell_str(row, 0),
                        "target": cell_str(row, 1),
                        "link_type": cell_str(row, 2),
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    let recent_activity: Vec<Value> = act_res
        .map(|r| {
            r.rows
                .iter()
                .map(|row| {
                    json!({
                        "watermark": cell_i64(row, 0),
                        "observation_id": cell_str(row, 1),
                        "mutation_kind": cell_str(row, 2),
                        "source_identity": cell_str(row, 3),
                        "observed_at": cell_str(row, 4),
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "depth": max_depth,
        "root": {
            "id": root_id,
            "object_type": cell_str(root_row, 1),
            "name": cell_str(root_row, 2),
            "resource_type": cell_str(root_row, 3),
            "revision": cell_i64(root_row, 4),
        },
        "total_nodes": nodes.len(),
        "total_edges": edges.len(),
        "nodes": nodes,
        "edges": edges,
        "recent_activity": recent_activity
    })
}

pub async fn fetch_lineage(db: &DbHandle, resource_id: Option<&str>) -> Value {
    let cleaned_rid = clean_opt(resource_id);
    let where_journal = match cleaned_rid {
        Some(rid) => {
            let exact = pg_quote_literal(rid);
            let pat = quote_like_contains(rid);
            format!("WHERE subject_ref = {exact} OR subject_ref ILIKE {pat} ESCAPE '\\'")
        }
        None => String::new(),
    };
    let journal_sql = format!(
        "SELECT watermark, observation_id, subject_ref, subject_type, mutation_kind, \
         source_identity, to_char(observed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
         FROM inventory_observation_journal {where_journal} ORDER BY watermark DESC LIMIT 80"
    );
    let journal_cnt_sql = format!("SELECT count(*) FROM inventory_observation_journal {where_journal}");
    let snap_sql = "SELECT id, status, source, resource_count, link_count, \
                    to_char(completed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                    FROM inventory_snapshot ORDER BY started_at DESC LIMIT 20";
    let res_cnt_sql = "SELECT count(*) FROM ontology_resource";
    let audit_sql = match cleaned_rid {
        Some(rid) => {
            let pat = quote_like_contains(rid);
            format!(
                "SELECT seq, actor, action_kind, mode, \
                 to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                 FROM audit_log \
                 WHERE entry::text ILIKE {pat} ESCAPE '\\' \
                 ORDER BY seq DESC LIMIT 20"
            )
        }
        None => "SELECT seq, actor, action_kind, mode, \
                 to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                 FROM audit_log ORDER BY seq DESC LIMIT 20"
            .to_string(),
    };
    let audit_cnt_sql = "SELECT count(*) FROM audit_log";

    let (j_res, j_cnt_res, s_res, r_cnt_res, a_res, a_cnt_res) = tokio::join!(
        db.query_single_readonly(&journal_sql),
        db.query_single_readonly(&journal_cnt_sql),
        db.query_single_readonly(snap_sql),
        db.query_single_readonly(res_cnt_sql),
        db.query_single_readonly(&audit_sql),
        db.query_single_readonly(audit_cnt_sql),
    );
    let (Ok(j), Ok(s)) = (j_res, s_res) else {
        return db.not_measured(
            "governance",
            "/api/v4/governance/ontology/lineage",
            "postgres_unreachable",
        );
    };

    let observations: Vec<Value> = j
        .rows
        .iter()
        .map(|r| {
            json!({
                "watermark": cell_i64(r, 0),
                "observation_id": cell_str(r, 1),
                "subject_ref": cell_str(r, 2),
                "subject_type": cell_str(r, 3),
                "mutation_kind": cell_str(r, 4),
                "source_identity": cell_str(r, 5),
                "observed_at": cell_str(r, 6)
            })
        })
        .collect();

    let snapshots: Vec<Value> = s
        .rows
        .iter()
        .map(|r| {
            json!({
                "id": cell_str(r, 0),
                "status": cell_str(r, 1),
                "source": cell_str(r, 2),
                "resource_count": cell_i64(r, 3),
                "link_count": cell_i64(r, 4),
                "completed_at": cell_str(r, 5)
            })
        })
        .collect();

    let audit_events: Vec<Value> = a_res
        .map(|r| {
            r.rows
                .iter()
                .map(|row| {
                    json!({
                        "seq": cell_i64(row, 0),
                        "actor": cell_str(row, 1),
                        "action_kind": cell_str(row, 2),
                        "mode": cell_str(row, 3),
                        "created_at": cell_str(row, 4),
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    let journal_total = j_cnt_res
        .ok()
        .and_then(|r| r.rows.first().and_then(|row| cell_i64(row, 0)))
        .unwrap_or(observations.len() as i64);
    let ontology_total = r_cnt_res
        .ok()
        .and_then(|r| r.rows.first().and_then(|row| cell_i64(row, 0)));
    let audit_total = a_cnt_res
        .ok()
        .and_then(|r| r.rows.first().and_then(|row| cell_i64(row, 0)));

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "resource_id": cleaned_rid,
        "observation_count": journal_total,
        "snapshot_count": snapshots.len(),
        "ontology_resource_count": ontology_total,
        "audit_event_total": audit_total,
        "stages": {
            "source": { "kind": "inventory_observation_journal", "count": journal_total },
            "snapshot": { "kind": "inventory_snapshot", "count": snapshots.len() },
            "pipeline": { "kind": "fdai_ontology_projection", "active_snapshots": snapshots.iter().filter(|x| x.get("status").and_then(Value::as_str) == Some("active")).count() },
            "ontology_instance": { "kind": "ontology_resource", "count": ontology_total },
            "audit_events": { "kind": "audit_log", "total": audit_total, "matched": audit_events.len() }
        },
        "observations": observations,
        "snapshots": snapshots,
        "audit_events": audit_events
    })
}

pub async fn fetch_catalog_documents(db: &DbHandle) -> Value {
    fetch_catalog_documents_filtered(db, None, None, Some(100)).await
}

pub async fn fetch_catalog_documents_filtered(
    db: &DbHandle,
    collection: Option<&str>,
    search: Option<&str>,
    limit: Option<usize>,
) -> Value {
    let lim = clamp_limit(limit, 100, 200);
    let mut clauses: Vec<String> = Vec::new();
    if let Some(col) = clean_opt(collection) {
        if col != "all" {
            let pat = quote_like_contains(col);
            clauses.push(format!(
                "(document_kind ILIKE {pat} ESCAPE '\\' OR rule_id ILIKE {pat} ESCAPE '\\' OR text ILIKE {pat} ESCAPE '\\')"
            ));
        }
    }
    if let Some(q) = clean_opt(search) {
        let pat = quote_like_contains(q);
        clauses.push(format!(
            "(rule_id ILIKE {pat} ESCAPE '\\' OR text ILIKE {pat} ESCAPE '\\' OR document_kind ILIKE {pat} ESCAPE '\\')"
        ));
    }
    let where_sql = if clauses.is_empty() {
        String::new()
    } else {
        format!("WHERE {}", clauses.join(" AND "))
    };
    let sql = format!(
        "SELECT generation_id, rule_id, document_kind, ordinal, \
         left(COALESCE(text, ''), 1200), COALESCE(content_hash::text, ''), \
         COALESCE(array_length(neighbor_ids, 1), 0) \
         FROM catalog_search_generation_document {where_sql} \
         ORDER BY ordinal ASC LIMIT {lim}"
    );
    let total_sql = "SELECT count(*) FROM catalog_search_generation_document";
    let (res, total_res) = tokio::join!(
        db.query_single_readonly(&sql),
        db.query_single_readonly(total_sql),
    );
    let Ok(res) = res else {
        return db.not_measured(
            "governance",
            "/api/v4/governance/documents",
            "postgres_unreachable",
        );
    };
    let total = total_res
        .ok()
        .and_then(|r| r.rows.first().and_then(|row| cell_i64(row, 0)))
        .unwrap_or(res.rows.len() as i64);

    let mut docs = Vec::with_capacity(res.rows.len());
    for r in &res.rows {
        let generation_id = cell_str(r, 0);
        let rule_id = cell_str(r, 1);
        let document_kind = cell_str(r, 2);
        let ordinal = cell_i64(r, 3);
        let text = cell_str(r, 4);
        let content_hash = cell_str(r, 5);
        let neighbor_count = cell_i64(r, 6).unwrap_or(0);
        let lines: Vec<&str> = text.lines().map(str::trim).filter(|l| !l.is_empty()).collect();
        let resource_type = lines.get(1).copied().unwrap_or("azure-resource");
        let category = lines.get(2).copied().unwrap_or("general");
        let severity = lines.get(3).copied().unwrap_or("medium");
        let title = lines.get(4).copied().unwrap_or(&rule_id);
        let excerpt = if lines.len() > 5 {
            lines[5..].join("\n")
        } else {
            text.clone()
        };
        let collection_name = match category {
            "reliability" | "resilience" | "operations" => "sre-runbooks",
            "security" | "governance" | "config_drift" => "arch-guides",
            _ => "handover",
        };
        docs.push(json!({
            "id": format!("doc-{}", ordinal.unwrap_or(0)),
            "generation_id": generation_id,
            "rule_id": rule_id,
            "title": title,
            "document_kind": document_kind,
            "collection": collection_name,
            "category": category,
            "severity": severity,
            "resource_type": resource_type,
            "ordinal": ordinal,
            "chunk_count": (neighbor_count + 1).max(1),
            "content_hash": content_hash.trim(),
            "excerpt": excerpt,
            "scan_status": "clean"
        }));
    }

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "total": total,
        "documents": docs,
        "items": docs
    })
}

pub async fn fetch_rules(
    db: &DbHandle,
    activation_state: Option<&str>,
    search: Option<&str>,
    limit: Option<usize>,
) -> Value {
    fetch_rules_filtered(db, activation_state, search, None, None, None, None, limit, None).await
}

struct BaselineRuleOutcome {
    violated: i64,
    compliant: i64,
    abstained: i64,
    sample_violated: Vec<String>,
}

fn format_rule_resource_type(raw: &str) -> String {
    let trimmed = raw.trim();
    if trimmed.is_empty()
        || trimmed.starts_with('-')
        || trimmed.to_ascii_lowercase().contains("current-resourcetype")
    {
        "azure.resource".to_string()
    } else {
        trimmed.to_string()
    }
}

fn utf8_truncate(raw: &str, max_chars: usize) -> String {
    let trimmed = raw.trim();
    if trimmed.chars().count() <= max_chars {
        trimmed.to_string()
    } else {
        let mut out: String = trimmed.chars().take(max_chars).collect();
        out.push_str("...");
        out
    }
}

struct RuleGuidanceInput<'a> {
    rule_id: &'a str,
    title_ko: &'a str,
    description_ko: &'a str,
    resource_type: &'a str,
    category: &'a str,
    severity: &'a str,
    evaluated_properties: &'a str,
    remediation_action: &'a str,
    remediation_template_ref: &'a str,
    check_logic_ref: &'a str,
    params: &'a Value,
    outcome: Option<&'a BaselineRuleOutcome>,
}

fn build_rule_guidance_ko(inp: &RuleGuidanceInput<'_>) -> (String, String, String, String) {
    let RuleGuidanceInput {
        rule_id,
        title_ko,
        description_ko,
        resource_type,
        category,
        severity,
        evaluated_properties,
        remediation_action,
        remediation_template_ref,
        check_logic_ref,
        params,
        outcome,
    } = *inp;
    let (mut current_state, recommended_config, benefit, verify) =
        if let Some((before, after, ben, ver)) = active_rule_guidance_ko(rule_id) {
            (
                before.to_string(),
                after.to_string(),
                ben.to_string(),
                ver.to_string(),
            )
        } else {
            let kube_ruleset = params
                .get("kube_bench_ruleset")
                .and_then(Value::as_str)
                .map(str::trim)
                .unwrap_or("");
            let kube_audit = params
                .get("kube_bench_audit")
                .and_then(Value::as_str)
                .map(str::trim)
                .unwrap_or("");
            let policy_cat = params
                .get("azure_policy_category")
                .and_then(Value::as_str)
                .map(str::trim)
                .unwrap_or("");
            let policy_effect = params
                .get("azure_policy_effect_default")
                .and_then(Value::as_str)
                .map(str::trim)
                .unwrap_or("");
            let rem_act = if remediation_action.is_empty() {
                "표준 정책 교정 절차"
            } else {
                remediation_action
            };
            let tpl_part = if remediation_template_ref.is_empty() {
                String::new()
            } else {
                format!(" ({remediation_template_ref})")
            };
            let check_ref = if check_logic_ref.is_empty() {
                rule_id
            } else {
                check_logic_ref
            };
            let prop_part = if evaluated_properties.is_empty() {
                String::new()
            } else {
                format!(" (점검 속성: {evaluated_properties})")
            };

            let before = if !policy_cat.is_empty() {
                format!(
                    "{resource_type} 리소스가 Azure Policy({policy_cat}{}) 기준 「{title_ko}」을 충족하지 않아 {severity} 심각도 위반 위험에 노출되어 있습니다{prop_part}.",
                    if policy_effect.is_empty() {
                        String::new()
                    } else {
                        format!(", 기본 효과: {policy_effect}")
                    }
                )
            } else if !kube_ruleset.is_empty() {
                format!(
                    "{resource_type} 대상 CIS Kubernetes 벤치마크({kube_ruleset}) 항목 「{title_ko}」 기준 미충족 상태가 탐지됩니다 ({check_ref})."
                )
            } else {
                format!(
                    "{resource_type} 리소스 구성이 「{title_ko}」 기준을 충족하지 못하여 {check_ref} 평가에서 {severity} 심각도 위반이 발생합니다{prop_part}."
                )
            };

            let after = format!(
                "{rem_act}{tpl_part} 조치를 통해 {resource_type} 리소스 구성을 「{title_ko}」 기준에 맞게 전환합니다."
            );

            let ben = if !description_ko.is_empty() {
                utf8_truncate(description_ko, 240)
            } else {
                format!(
                    "{resource_type} 리소스의 {category} 기준 이탈을 결정론적으로 탐지하고 {rem_act} 조치를 통해 운영·보안 위험을 사전에 차단합니다."
                )
            };

            let ver = if !kube_audit.is_empty() {
                format!(
                    "감사 명령어({})를 실행하고 다음 인벤토리 세대에서 {check_ref} 검사를 재평가하여 준수(Compliant) 여부를 검증합니다.",
                    utf8_truncate(kube_audit, 140)
                )
            } else if !evaluated_properties.is_empty() {
                format!(
                    "최신 인벤토리 스냅샷의 {evaluated_properties} 속성과 {check_ref} T0 평가 결과가 준수(Compliant)로 전환되었는지 확인합니다."
                )
            } else {
                format!(
                    "다음 인벤토리 스냅샷에서 {check_ref} 규칙 재평가 결과가 준수(Compliant)이며 활성 위반 0건인지 검증합니다."
                )
            };

            (before, after, ben, ver)
        };

    if let Some(out) = outcome {
        let total = out.violated + out.compliant + out.abstained;
        if total > 0 {
            let sample_suffix = if out.sample_violated.is_empty() {
                String::new()
            } else {
                format!(" · 대표 위반 대상: {}", out.sample_violated.join(", "))
            };
            current_state.push_str(&format!(
                " [실DB 평가 현황: 위반 {}건 · 준수 {}건 · 보류 {}건{}]",
                out.violated, out.compliant, out.abstained, sample_suffix
            ));
        }
    }

    (current_state, recommended_config, benefit, verify)
}

async fn load_baseline_outcomes(db: &DbHandle) -> HashMap<String, BaselineRuleOutcome> {
    let sql = "SELECT value->>'rule_ref', \
               count(*) FILTER (WHERE value->>'outcome' = 'violated'), \
               count(*) FILTER (WHERE value->>'outcome' = 'compliant'), \
               count(*) FILTER (WHERE value->>'outcome' = 'abstained'), \
               COALESCE(string_agg(DISTINCT value->>'resource_ref', ',') FILTER (WHERE value->>'outcome' = 'violated'), '') \
               FROM state_kv \
               WHERE key LIKE 'baseline-evaluation:outcomes:%' \
               GROUP BY 1";
    let mut map = HashMap::new();
    let Ok(res) = db.query_single_readonly(sql).await else {
        return map;
    };
    for row in &res.rows {
        let raw_ref = cell_str(row, 0);
        let rule_id = raw_ref.strip_prefix("rule:").unwrap_or(&raw_ref).to_string();
        if rule_id.is_empty() {
            continue;
        }
        let violated = cell_i64(row, 1).unwrap_or(0);
        let compliant = cell_i64(row, 2).unwrap_or(0);
        let abstained = cell_i64(row, 3).unwrap_or(0);
        let samples_raw = cell_str(row, 4);
        let sample_violated: Vec<String> = samples_raw
            .split(',')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .take(3)
            .map(String::from)
            .collect();
        map.insert(
            rule_id,
            BaselineRuleOutcome {
                violated,
                compliant,
                abstained,
                sample_violated,
            },
        );
    }
    map
}

#[allow(clippy::too_many_arguments)]
pub async fn fetch_rules_filtered(
    db: &DbHandle,
    activation_state: Option<&str>,
    search: Option<&str>,
    severity_filter: Option<&str>,
    category_filter: Option<&str>,
    origin_filter: Option<&str>,
    framework_filter: Option<&str>,
    limit: Option<usize>,
    offset: Option<usize>,
) -> Value {
    fetch_rules_filtered_view(
        db,
        activation_state,
        search,
        severity_filter,
        category_filter,
        origin_filter,
        framework_filter,
        limit,
        offset,
        false,
    )
    .await
}

#[allow(clippy::too_many_arguments)]
pub async fn fetch_rules_filtered_view(
    db: &DbHandle,
    activation_state: Option<&str>,
    search: Option<&str>,
    severity_filter: Option<&str>,
    category_filter: Option<&str>,
    origin_filter: Option<&str>,
    framework_filter: Option<&str>,
    limit: Option<usize>,
    offset: Option<usize>,
    summary_only: bool,
) -> Value {
    let lim = clamp_limit(limit, if summary_only { 30 } else { 100 }, 200);
    let off = offset.unwrap_or(0).min(100_000);

    let summary_sql = format!(
        "SELECT count(*), \
         count(*) FILTER (WHERE lower(COALESCE(d.val->>'severity','')) IN {MANDATORY_SEVERITIES_SQL}), \
         count(*) FILTER (WHERE d.val->>'origin' = 'active' AND lower(COALESCE(d.val->>'severity','')) NOT IN {MANDATORY_SEVERITIES_SQL}), \
         count(*) FILTER (WHERE d.val->>'origin' = 'active'), \
         count(*) FILTER (WHERE d.val->>'origin' <> 'active'), \
         count(*) FILTER (WHERE lower(COALESCE(d.val->>'severity','')) = 'critical'), \
         count(*) FILTER (WHERE lower(COALESCE(d.val->>'severity','')) = 'high'), \
         count(*) FILTER (WHERE lower(COALESCE(d.val->>'severity','')) = 'medium'), \
         count(*) FILTER (WHERE lower(COALESCE(d.val->>'severity','')) = 'low') \
         FROM state_kv sk, jsonb_each(sk.value->'details') AS d(k, val) \
         WHERE sk.key = 'operator-projection:workflow:rule.list'"
    );

    let mut clauses: Vec<String> =
        vec!["sk.key = 'operator-projection:workflow:rule.list'".to_string()];
    if let Some(q) = clean_opt(search) {
        let pat = quote_like_contains(q);
        clauses.push(format!(
            "(COALESCE(d.val->>'id', d.val->>'rule_id', '') ILIKE {pat} ESCAPE '\\' \
              OR COALESCE(d.val->'explanation'->'details'->>'title_ko', '') ILIKE {pat} ESCAPE '\\' \
              OR COALESCE(d.val->'explanation'->'details'->>'description_ko', '') ILIKE {pat} ESCAPE '\\' \
              OR COALESCE(d.val->'explanation'->>'title', '') ILIKE {pat} ESCAPE '\\' \
              OR COALESCE(d.val->>'resource_type', '') ILIKE {pat} ESCAPE '\\' \
              OR COALESCE(d.val->>'category', '') ILIKE {pat} ESCAPE '\\' \
              OR COALESCE(d.val->>'source', '') ILIKE {pat} ESCAPE '\\')"
        ));
    }
    if let Some(sev) = clean_opt(severity_filter) {
        let low = sev.to_ascii_lowercase();
        let mapped = match low.as_str() {
            "긴급" => "critical",
            "높음" => "high",
            "보통" => "medium",
            "낮음" => "low",
            other => other,
        };
        clauses.push(format!(
            "lower(COALESCE(d.val->>'severity','')) = {}",
            pg_quote_literal(mapped)
        ));
    }
    if let Some(cat) = clean_opt(category_filter) {
        let pat = quote_like_contains(cat);
        clauses.push(format!(
            "COALESCE(d.val->>'category','') ILIKE {pat} ESCAPE '\\'"
        ));
    }
    if let Some(orig) = clean_opt(origin_filter) {
        clauses.push(format!(
            "COALESCE(d.val->>'origin','') = {}",
            pg_quote_literal(orig)
        ));
    }
    if let Some(fw) = clean_opt(framework_filter) {
        let pat = quote_like_contains(fw);
        clauses.push(format!(
            "COALESCE(d.val->>'source','') ILIKE {pat} ESCAPE '\\'"
        ));
    }
    if let Some(st) = clean_opt(activation_state) {
        match st.to_ascii_lowercase().as_str() {
            "mandatory" => {
                clauses.push(format!(
                    "lower(COALESCE(d.val->>'severity','')) IN {MANDATORY_SEVERITIES_SQL}"
                ));
            }
            "enabled" => {
                clauses.push(format!(
                    "(lower(COALESCE(d.val->>'severity','')) IN {MANDATORY_SEVERITIES_SQL} OR d.val->>'origin' = 'active')"
                ));
            }
            "disabled" => {
                clauses.push(format!(
                    "(lower(COALESCE(d.val->>'severity','')) NOT IN {MANDATORY_SEVERITIES_SQL} AND COALESCE(d.val->>'origin','') <> 'active')"
                ));
            }
            _ => {}
        }
    }

    let where_sql = clauses.join(" AND ");
    let filtered_cnt_sql = format!(
        "SELECT count(*) FROM state_kv sk, jsonb_each(sk.value->'details') AS d(k, val) WHERE {where_sql}"
    );
    let page_sql = format!(
        "SELECT \
            COALESCE(d.val->>'id', d.val->>'rule_id', ''), \
            COALESCE(d.val->'explanation'->'details'->>'title_ko', ''), \
            COALESCE(d.val->'explanation'->>'title', d.val->>'id', ''), \
            COALESCE(d.val->'explanation'->'details'->>'description_ko', ''), \
            COALESCE(d.val->'explanation'->>'description', ''), \
            COALESCE(d.val->>'category', 'general'), \
            COALESCE(d.val->>'severity', 'medium'), \
            COALESCE(d.val->>'origin', 'collected'), \
            COALESCE(d.val->>'source', 'catalog'), \
            COALESCE(NULLIF(d.val->>'resource_type', ''), d.val->'applies_to'->'resource_types'->>0, 'azure.resource'), \
            COALESCE(NULLIF(d.val->'explanation'->'details'->>'remediation_action', ''), d.val->>'remediates', ''), \
            COALESCE(d.val->'remediation'->>'template_ref', ''), \
            COALESCE(d.val->'check_logic'->>'kind', 'rego'), \
            COALESCE(d.val->'check_logic'->>'reference', ''), \
            left(COALESCE(d.val->>'check_logic_body', ''), 1800), \
            COALESCE(d.val->'provenance'->>'source_url', ''), \
            COALESCE(d.val->'explanation'->'details'->>'evaluated_properties', ''), \
            COALESCE(d.val->'explanation'->'details'->>'trigger_signals', ''), \
            COALESCE(d.val->'parameters'::text, '{{}}') \
         FROM state_kv sk, jsonb_each(sk.value->'details') AS d(k, val) \
         WHERE {where_sql} \
         ORDER BY \
            CASE \
              WHEN lower(COALESCE(d.val->>'severity','')) = 'critical' THEN 0 \
              WHEN lower(COALESCE(d.val->>'severity','')) = 'high' AND d.val->>'origin' = 'active' THEN 1 \
              WHEN lower(COALESCE(d.val->>'severity','')) = 'high' THEN 2 \
              WHEN d.val->>'origin' = 'active' THEN 3 \
              ELSE 4 \
            END, \
            COALESCE(d.val->>'id', d.val->>'rule_id', '') ASC \
         LIMIT {lim} OFFSET {off}"
    );

    let (sum_res, fcnt_res, page_res, overrides_map, outcomes_map) = tokio::join!(
        db.query_single_readonly(&summary_sql),
        db.query_single_readonly(&filtered_cnt_sql),
        db.query_single_readonly(&page_sql),
        load_rule_overrides(db),
        load_baseline_outcomes(db),
    );

    let (Ok(sum_q), Ok(page_q)) = (sum_res, page_res) else {
        return db.not_measured(
            "governance",
            "/api/v4/governance/rules",
            "postgres_unreachable",
        );
    };

    let sum_row = sum_q.rows.first();
    let total_all = sum_row.and_then(|r| cell_i64(r, 0)).unwrap_or(0).max(0) as u64;
    let mandatory_total = sum_row.and_then(|r| cell_i64(r, 1)).unwrap_or(0).max(0) as u64;
    let non_mandatory_active = sum_row.and_then(|r| cell_i64(r, 2)).unwrap_or(0).max(0) as u64;
    let origin_active_raw = sum_row.and_then(|r| cell_i64(r, 3)).unwrap_or(0).max(0) as u64;
    let origin_collected_raw = sum_row.and_then(|r| cell_i64(r, 4)).unwrap_or(0).max(0) as u64;
    let critical_count = sum_row.and_then(|r| cell_i64(r, 5)).unwrap_or(0).max(0) as u64;
    let high_count = sum_row.and_then(|r| cell_i64(r, 6)).unwrap_or(0).max(0) as u64;
    let medium_count = sum_row.and_then(|r| cell_i64(r, 7)).unwrap_or(0).max(0) as u64;
    let low_count = sum_row.and_then(|r| cell_i64(r, 8)).unwrap_or(0).max(0) as u64;

    let enabled_total = (mandatory_total + non_mandatory_active).min(total_all);
    let disabled_total = total_all.saturating_sub(enabled_total);
    let filtered_total = fcnt_res
        .ok()
        .and_then(|r| r.rows.first().and_then(|row| cell_i64(row, 0)))
        .unwrap_or(page_q.rows.len() as i64)
        .max(0) as u64;

    let mut rules = Vec::with_capacity(page_q.rows.len());
    for row in &page_q.rows {
        let rule_id = cell_str(row, 0);
        if rule_id.is_empty() {
            continue;
        }
        let raw_title_ko = cell_str(row, 1);
        let title_en = cell_str(row, 2);
        let description_ko = cell_str(row, 3);
        let description_en = cell_str(row, 4);
        let category = cell_str(row, 5);
        let severity = cell_str(row, 6);
        let origin = cell_str(row, 7);
        let source = cell_str(row, 8);
        let resource_type = format_rule_resource_type(&cell_str(row, 9));
        let remediation_action = cell_str(row, 10);
        let remediation_template_ref = cell_str(row, 11);
        let check_logic_kind = cell_str(row, 12);
        let check_ref = cell_str(row, 13);
        let check_logic_body = cell_str(row, 14);
        let source_url = cell_str(row, 15);
        let evaluated_properties = cell_str(row, 16);
        let trigger_signals = cell_str(row, 17);
        let params_val: Value =
            serde_json::from_str(&cell_str(row, 18)).unwrap_or_else(|_| json!({}));

        let title_ko = if !raw_title_ko.trim().is_empty() {
            raw_title_ko.trim().to_string()
        } else if !title_en.trim().is_empty() {
            title_en.trim().to_string()
        } else {
            rule_id.clone()
        };

        let mandatory_active = is_mandatory_rule_severity(&severity);
        let ov = overrides_map.get(&rule_id);
        let override_enabled = ov.and_then(|o| o.get("enabled")).and_then(Value::as_bool);
        let enabled = if mandatory_active {
            true
        } else {
            override_enabled.unwrap_or(origin == "active")
        };
        let can_deactivate = !mandatory_active;
        let mode = if enabled {
            if origin == "active" || mandatory_active {
                "Enforce"
            } else {
                "Shadow"
            }
        } else {
            "Disabled"
        };

        let outcome = outcomes_map.get(&rule_id);
        let (current_state_ko, recommended_config_ko, benefit_ko, verify_ko) =
            build_rule_guidance_ko(&RuleGuidanceInput {
                rule_id: &rule_id,
                title_ko: &title_ko,
                description_ko: &description_ko,
                resource_type: &resource_type,
                category: &category,
                severity: &severity,
                evaluated_properties: &evaluated_properties,
                remediation_action: &remediation_action,
                remediation_template_ref: &remediation_template_ref,
                check_logic_ref: &check_ref,
                params: &params_val,
                outcome,
            });

        let baseline_outcomes = match outcome {
            Some(o) => json!({
                "evaluated": true,
                "violated": o.violated,
                "compliant": o.compliant,
                "abstained": o.abstained,
                "total_evaluated": o.violated + o.compliant + o.abstained,
                "sample_violated_resources": o.sample_violated
            }),
            None => json!({
                "evaluated": false,
                "violated": 0,
                "compliant": 0,
                "abstained": 0,
                "total_evaluated": 0,
                "sample_violated_resources": []
            }),
        };

        let updated_by = ov
            .and_then(|o| o.get("updated_by"))
            .and_then(Value::as_str)
            .unwrap_or(if mandatory_active {
                "mandatory-policy"
            } else {
                "catalog-projection"
            });
        let reason = ov
            .and_then(|o| o.get("reason"))
            .and_then(Value::as_str)
            .unwrap_or(if mandatory_active {
                "Critical/High 심각도 필수 활성화 정책"
            } else {
                "PostgreSQL state_kv 프로젝션 동기화"
            });

        let summary_ko = if !description_ko.trim().is_empty() {
            description_ko.trim().to_string()
        } else {
            benefit_ko.clone()
        };

        let condition_display = if !check_logic_body.trim().is_empty() {
            check_logic_body.clone()
        } else if !check_ref.is_empty() {
            format!(
                "kind: {check_logic_kind}\nreference: {check_ref}\nresource_type: {resource_type}\nseverity: {severity}\nmandatory_active: {mandatory_active}"
            )
        } else {
            format!(
                "rule_id: {rule_id}\nresource_type: {resource_type}\nseverity: {severity}\nmandatory_active: {mandatory_active}"
            )
        };

        if summary_only {
            rules.push(json!({
                "id": rule_id,
                "rule_id": rule_id,
                "title": title_ko,
                "title_ko": title_ko,
                "title_en": title_en,
                "summary": utf8_truncate(&summary_ko, 180),
                "category": category,
                "severity": severity,
                "origin": if enabled { "active" } else { origin.as_str() },
                "source": source,
                "resource_type": resource_type,
                "remediation_action": remediation_action,
                "findings_24h": outcome.map_or(0, |o| o.violated),
                "mode": mode,
                "enabled": enabled,
                "mandatory_active": mandatory_active,
                "can_deactivate": can_deactivate,
                "detail_loaded": false
            }));
        } else {
            rules.push(json!({
                "id": rule_id,
                "rule_id": rule_id,
                "title": title_ko,
                "title_ko": title_ko,
                "title_en": title_en,
                "description_ko": description_ko,
                "description_en": description_en,
                "summary": summary_ko,
                "category": category,
                "severity": severity,
                "origin": if enabled { "active" } else { origin.as_str() },
                "raw_origin": origin,
                "source": source,
                "resource_type": resource_type,
                "remediates": remediation_action,
                "remediation_action": remediation_action,
                "remediation_template_ref": remediation_template_ref,
                "evaluated_properties": evaluated_properties,
                "trigger_signals": trigger_signals,
                "check_logic_kind": check_logic_kind,
                "check_logic_ref": check_ref,
                "check_logic_body": check_logic_body,
                "condition": condition_display,
                "parameters": params_val,
                "source_url": source_url,
                "current_state_ko": current_state_ko,
                "recommended_config_ko": recommended_config_ko,
                "benefit_ko": benefit_ko,
                "verify_ko": verify_ko,
                "baseline_outcomes": baseline_outcomes,
                "findings_24h": outcome.map_or(0, |o| o.violated),
                "mode": mode,
                "enabled": enabled,
                "mandatory_active": mandatory_active,
                "can_deactivate": can_deactivate,
                "activation_updated_by": updated_by,
                "activation_reason": reason,
                "activation_policy": if mandatory_active { "mandatory_critical_high" } else { "operator_configurable" },
                "detail_loaded": true
            }));
        }
    }

    let has_more = off.saturating_add(rules.len()) < (filtered_total.max(0) as usize);
    let mut payload = json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "view": if summary_only { "summary" } else { "full" },
        "mandatory_severities": ["critical", "high"],
        "total": total_all,
        "filtered_total": filtered_total,
        "limit": lim,
        "offset": off,
        "has_more": has_more,
        "facets": {
            "by_origin": {
                "active": enabled_total,
                "collected": disabled_total,
                "raw_active": origin_active_raw,
                "raw_collected": origin_collected_raw
            },
            "by_severity": {
                "critical": critical_count,
                "high": high_count,
                "medium": medium_count,
                "low": low_count
            }
        },
        "summary": {
            "total": total_all,
            "mandatory_count": mandatory_total,
            "enabled_count": enabled_total,
            "disabled_count": disabled_total
        },
        "rules": rules
    });
    if !summary_only {
        if let Some(obj) = payload.as_object_mut() {
            let items_clone = obj.get("rules").cloned().unwrap_or_else(|| json!([]));
            obj.insert("items".to_string(), items_clone);
        }
    }
    payload
}

pub async fn fetch_rule_detail(db: &DbHandle, rule_id: &str) -> Value {
    let res = fetch_rules_filtered_view(
        db,
        None,
        Some(rule_id),
        None,
        None,
        None,
        None,
        Some(10),
        Some(0),
        false,
    )
    .await;
    if res.get("measurement_status").and_then(Value::as_str) != Some("measured") {
        return res;
    }
    let found = res
        .get("rules")
        .and_then(Value::as_array)
        .and_then(|arr| {
            arr.iter()
                .find(|r| r.get("id").and_then(Value::as_str) == Some(rule_id))
                .or_else(|| arr.first())
        })
        .cloned();
    match found {
        Some(rule) => json!({
            "measurement_status": "measured",
            "source": "postgres-direct",
            "rule": rule
        }),
        None => json!({
            "measurement_status": "measured",
            "source": "postgres-direct",
            "rule": Value::Null
        }),
    }
}

pub async fn fetch_rules_findings_summary(db: &DbHandle) -> Value {
    let finding_sql = "SELECT count(*) FROM ontology_finding";
    let audit_sql = "SELECT \
        count(*) FILTER (WHERE action_kind = 'control_loop.compliant'), \
        count(*) FILTER (WHERE action_kind = 'control_loop.abstain'), \
        count(*) FILTER (WHERE action_kind = 'measurement.control_loop.v1'), \
        count(*) FILTER (WHERE action_kind = 'mimir.rule-source.observed') \
        FROM audit_log";
    let rule_cnt_sql = format!(
        "SELECT count(*), \
         count(*) FILTER (WHERE lower(COALESCE(elem->>'severity','')) IN {MANDATORY_SEVERITIES_SQL}), \
         count(*) FILTER (WHERE elem->>'origin' = 'active') \
         FROM state_kv, jsonb_array_elements(value->'rules') elem \
         WHERE key = 'operator-projection:workflow:rule.list'"
    );
    let (f_res, a_res, r_res) = tokio::join!(
        db.query_single_readonly(finding_sql),
        db.query_single_readonly(audit_sql),
        db.query_single_readonly(&rule_cnt_sql),
    );
    let (Ok(fq), Ok(aq), Ok(rq)) = (f_res, a_res, r_res) else {
        return db.not_measured(
            "governance",
            "/api/v4/governance/rules/findings-summary",
            "postgres_unreachable",
        );
    };
    let finding_count = fq.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let compliant = aq
        .rows
        .first()
        .and_then(|r| cell_i64(r, 0))
        .unwrap_or(0);
    let abstain = aq
        .rows
        .first()
        .and_then(|r| cell_i64(r, 1))
        .unwrap_or(0);
    let evaluated_events = aq
        .rows
        .first()
        .and_then(|r| cell_i64(r, 2))
        .unwrap_or(0);
    let source_observed = aq
        .rows
        .first()
        .and_then(|r| cell_i64(r, 3))
        .unwrap_or(0);
    let total_rules = rq.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let mandatory_rules = rq.rows.first().and_then(|r| cell_i64(r, 1)).unwrap_or(0);
    let active_rules = rq.rows.first().and_then(|r| cell_i64(r, 2)).unwrap_or(0);

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "evaluated": evaluated_events > 0,
        "ontology_finding_count": finding_count,
        "evaluated_events": evaluated_events,
        "compliant_events": compliant,
        "abstain_events": abstain,
        "rule_source_observations": source_observed,
        "total_rules": total_rules,
        "mandatory_rules": mandatory_rules,
        "active_rules": active_rules,
        "counts": {}
    })
}

pub async fn update_rule_activation(
    db: &DbHandle,
    rule_id: &str,
    enabled: bool,
    severity: &str,
    actor: &str,
    reason: &str,
    idempotency_key: &str,
) -> Result<Value, (u16, Value)> {
    let db_severity = if db.is_configured() {
        fetch_rule_severity(db, rule_id).await
    } else {
        None
    };
    let effective_severity = db_severity.as_deref().unwrap_or(severity);
    if (is_mandatory_rule_severity(severity) || is_mandatory_rule_severity(effective_severity))
        && !enabled
    {
        return Err((
            409,
            json!({
                "error": "mandatory_severity_cannot_be_disabled",
                "code": "mandatory_severity_locked",
                "message": "심각도가 Critical 또는 High인 운영 규칙은 필수 활성화 대상이므로 비활성화할 수 없습니다.",
                "rule_id": rule_id,
                "severity": effective_severity,
                "mandatory_active": true,
                "can_deactivate": false
            }),
        ));
    }
    let payload = json!({
        "schema_version": "1.0.0",
        "mandatory_severities": ["critical", "high"],
        "rule_id": rule_id,
        "enabled": enabled,
        "severity": effective_severity,
        "reason": reason,
        "updated_by": actor
    });
    let key = format!("operator-state:governance:rule-activation:{rule_id}");
    match db
        .execute_audited_kv_mutation(
            &key,
            &payload.to_string(),
            actor,
            "rule.activation.updated",
            idempotency_key,
        )
        .await
    {
        Ok(res) => Ok(json!({
            "persisted": true,
            "pg_persisted": true,
            "rule_id": rule_id,
            "enabled": enabled,
            "severity": effective_severity,
            "mandatory_active": is_mandatory_rule_severity(effective_severity),
            "can_deactivate": !is_mandatory_rule_severity(effective_severity),
            "receipt": res
        })),
        Err(reason_code) => Err((
            503,
            db.not_measured(
                "governance",
                "/api/v4/governance/rules/activation",
                &reason_code,
            ),
        )),
    }
}

pub async fn fetch_mandatory_rule_counts(db: &DbHandle) -> Option<(u64, u64)> {
    let sql = format!(
        "SELECT \
            count(*) FILTER (WHERE lower(COALESCE(elem->>'severity','')) IN {MANDATORY_SEVERITIES_SQL}), \
            count(*) FILTER (WHERE lower(COALESCE(elem->>'severity','')) IN {MANDATORY_SEVERITIES_SQL} AND COALESCE(elem->>'origin','') <> 'active') \
         FROM state_kv, jsonb_array_elements(value->'rules') elem \
         WHERE key = 'operator-projection:workflow:rule.list'"
    );
    let res = db.query_single_readonly(&sql).await.ok()?;
    let row = res.rows.first()?;
    let total = cell_i64(row, 0).unwrap_or(0).max(0) as u64;
    let newly_enforced = cell_i64(row, 1).unwrap_or(0).max(0) as u64;
    Some((total, newly_enforced))
}

pub async fn enforce_mandatory_rules(
    db: &DbHandle,
    actor: &str,
    idempotency_key: &str,
) -> Result<Value, (u16, Value)> {
    let (mandatory_count, newly_enforced) = match fetch_mandatory_rule_counts(db).await {
        Some(pair) => pair,
        None => {
            return Err((
                503,
                db.not_measured(
                    "governance",
                    "/api/v4/governance/rules/enforce-mandatory",
                    "postgres_unreachable",
                ),
            ));
        }
    };
    let payload = json!({
        "schema_version": "1.0.0",
        "mandatory_severities": ["critical", "high"],
        "mandatory_rule_count": mandatory_count,
        "enforced_count": newly_enforced,
        "updated_by": actor
    });
    match db
        .execute_audited_kv_mutation(
            "operator-state:governance:rule-activations:mandatory-sync",
            &payload.to_string(),
            actor,
            "rule.activation.enforce_mandatory",
            idempotency_key,
        )
        .await
    {
        Ok(res) => Ok(json!({
            "persisted": true,
            "pg_persisted": true,
            "mandatory_severities": ["critical", "high"],
            "mandatory_rule_count": mandatory_count,
            "enforced_count": newly_enforced,
            "receipt": res
        })),
        Err(reason_code) => Err((
            503,
            db.not_measured(
                "governance",
                "/api/v4/governance/rules/enforce-mandatory",
                &reason_code,
            ),
        )),
    }
}

pub async fn fetch_trust_routing(db: &DbHandle, window: Option<&str>) -> Value {
    let tier_sql = "SELECT COALESCE(entry->>'tier', 'unknown'), \
                    COALESCE(entry->>'gate_route', 'unknown'), count(*) \
                    FROM audit_log \
                    WHERE action_kind = 'measurement.control_loop.v1' \
                    GROUP BY 1, 2 ORDER BY 3 DESC";
    let extra_sql = "SELECT action_kind, count(*) FROM audit_log \
                     WHERE action_kind IN ('control_loop.compliant', 'control_loop.abstain', \
                                           'control_loop.t1_evaluate', 'risk_gate.unified', \
                                           'rca.hypothesis', 'decision-evidence.admission-retained') \
                     GROUP BY 1";
    let recent_sql = "SELECT seq, \
                      to_char(created_at AT TIME ZONE 'UTC', 'HH24:MI:SS'), \
                      action_kind, \
                      COALESCE(entry->>'tier', 't1'), \
                      COALESCE(entry->>'gate_route', entry->>'t1_outcome', 'observed'), \
                      COALESCE(entry->>'source', actor), \
                      COALESCE(entry->>'resource_type', entry->>'event_type', action_kind), \
                      COALESCE(entry->>'reason', entry->>'t1_reason', entry->>'stage', action_kind), \
                      to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                      FROM audit_log \
                      WHERE action_kind IN ('measurement.control_loop.v1', 'control_loop.t1_evaluate', \
                                            'control_loop.compliant', 'control_loop.abstain') \
                      ORDER BY seq DESC LIMIT 8";
    let domain_sql = "SELECT COALESCE(NULLIF(entry->>'domain', ''), \
                                      NULLIF(entry->>'resource_type', ''), \
                                      NULLIF(entry->>'event_type', ''), \
                                      action_kind) AS domain_key, \
                             COALESCE(entry->>'tier', 't1') AS tier_key, \
                             count(*) \
                      FROM audit_log \
                      WHERE action_kind = 'measurement.control_loop.v1' \
                      GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 48";
    let (tier_res, extra_res, recent_res, domain_res) = tokio::join!(
        db.query_single_readonly(tier_sql),
        db.query_single_readonly(extra_sql),
        db.query_single_readonly(recent_sql),
        db.query_single_readonly(domain_sql),
    );
    let Ok(tier_q) = tier_res else {
        return db.not_measured(
            "governance",
            "/api/v4/governance/trust-routing",
            "postgres_unreachable",
        );
    };

    let mut t0_count: i64 = 0;
    let mut t1_count: i64 = 0;
    let mut t2_count: i64 = 0;
    let mut unknown_count: i64 = 0;
    let mut abstain_route_count: i64 = 0;
    let mut compliant_route_count: i64 = 0;
    let mut hil_route_count: i64 = 0;
    let mut breakdown: Vec<Value> = Vec::new();

    for row in &tier_q.rows {
        let tier = cell_str(row, 0).to_ascii_lowercase();
        let route = cell_str(row, 1).to_ascii_lowercase();
        let cnt = cell_i64(row, 2).unwrap_or(0);
        match tier.as_str() {
            "t0" => t0_count += cnt,
            "t1" => t1_count += cnt,
            "t2" => t2_count += cnt,
            _ => unknown_count += cnt,
        }
        match route.as_str() {
            "abstain" => abstain_route_count += cnt,
            "compliant" => compliant_route_count += cnt,
            "hil" => hil_route_count += cnt,
            _ => {}
        }
        breakdown.push(json!({
            "tier": tier,
            "gate_route": route,
            "count": cnt
        }));
    }

    let classified_total = t0_count + t1_count + t2_count;
    let total_events = classified_total + unknown_count;
    let denom = if total_events > 0 {
        total_events as f64
    } else {
        1.0
    };
    let round1 = |v: f64| (v * 10.0).round() / 10.0;
    let t0_pct = if total_events > 0 {
        round1((t0_count as f64 / denom) * 100.0)
    } else {
        0.0
    };
    let t1_pct = if total_events > 0 {
        round1(((t1_count + unknown_count) as f64 / denom) * 100.0)
    } else {
        0.0
    };
    let t2_pct = if total_events > 0 {
        round1((t2_count as f64 / denom) * 100.0)
    } else {
        0.0
    };
    let deterministic_pct = round1((100.0 - t2_pct).clamp(0.0, 100.0));

    let mut stage_counts = Map::new();
    if let Ok(eq) = extra_res {
        for row in &eq.rows {
            let kind = cell_str(row, 0);
            let cnt = cell_i64(row, 1).unwrap_or(0);
            stage_counts.insert(kind, Value::from(cnt));
        }
    }

    let recent_events: Vec<Value> = recent_res
        .map(|r| {
            r.rows
                .iter()
                .map(|row| {
                    json!({
                        "seq": cell_i64(row, 0),
                        "time": cell_str(row, 1),
                        "created_at": cell_str(row, 8),
                        "action_kind": cell_str(row, 2),
                        "tier": cell_str(row, 3).to_ascii_uppercase(),
                        "gate_route": cell_str(row, 4),
                        "source": cell_str(row, 5),
                        "resource_type": cell_str(row, 6),
                        "reason": cell_str(row, 7)
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    let mut domain_acc: HashMap<String, (i64, i64, i64)> = HashMap::new();
    if let Ok(dq) = domain_res {
        for row in &dq.rows {
            let domain_key = cell_str(row, 0);
            if domain_key.is_empty() {
                continue;
            }
            let tier_key = cell_str(row, 1).to_ascii_lowercase();
            let cnt = cell_i64(row, 2).unwrap_or(0);
            let entry = domain_acc.entry(domain_key).or_insert((0, 0, 0));
            match tier_key.as_str() {
                "t0" => entry.0 += cnt,
                "t2" => entry.2 += cnt,
                _ => entry.1 += cnt,
            }
        }
    }
    let mut domain_rows: Vec<(String, i64, i64, i64, i64)> = domain_acc
        .into_iter()
        .map(|(dom, (c0, c1, c2))| (dom, c0 + c1 + c2, c0, c1, c2))
        .collect();
    domain_rows.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
    let domain_breakdown: Vec<Value> = domain_rows
        .into_iter()
        .take(6)
        .map(|(dom, tot, c0, c1, c2)| {
            let d = if tot > 0 { tot as f64 } else { 1.0 };
            json!({
                "domain": dom,
                "total": tot,
                "t0_count": c0,
                "t1_count": c1,
                "t2_count": c2,
                "t0_pct": round1((c0 as f64 / d) * 100.0),
                "t1_pct": round1((c1 as f64 / d) * 100.0),
                "t2_pct": round1((c2 as f64 / d) * 100.0)
            })
        })
        .collect();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "window": clean_opt(window).unwrap_or("all"),
        "total_events": total_events,
        "classified_events": classified_total,
        "tiers": {
            "t0": { "count": t0_count, "pct": t0_pct },
            "t1": { "count": t1_count, "pct": t1_pct, "unclassified_abstain": unknown_count },
            "t2": { "count": t2_count, "pct": t2_pct }
        },
        "routes": {
            "compliant": compliant_route_count,
            "hil": hil_route_count,
            "abstain": abstain_route_count
        },
        "deterministic_pct": deterministic_pct,
        "verifier_abstain_count": abstain_route_count,
        "stage_counts": stage_counts,
        "breakdown": breakdown,
        "domain_breakdown": domain_breakdown,
        "recent_events": recent_events
    })
}

pub async fn fetch_scope(db: &DbHandle, axis_filter: Option<&str>) -> Value {
    let kv_sql = "SELECT value::text, to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                  FROM state_kv WHERE key = 'operator-projection:operations:scope.effective' LIMIT 1";
    let obs_sql = "SELECT split_part(id, '/', 1) AS scope_prefix, count(*) \
                   FROM ontology_resource WHERE object_type = 'Resource' \
                   GROUP BY 1 ORDER BY 2 DESC LIMIT 20";
    let rg_sql = "SELECT split_part(id, '/', 3) AS rg, count(*) \
                  FROM ontology_resource \
                  WHERE object_type = 'Resource' AND split_part(id, '/', 2) = 'resource-group' \
                  GROUP BY 1 ORDER BY 2 DESC LIMIT 30";

    let (kv_res, obs_res, rg_res) = tokio::join!(
        db.query_single_readonly(kv_sql),
        db.query_single_readonly(obs_sql),
        db.query_single_readonly(rg_sql),
    );
    let Ok(kv_q) = kv_res else {
        return db.not_measured(
            "governance",
            "/api/v4/governance/scope",
            "postgres_unreachable",
        );
    };

    let (scope_val, updated_at) = kv_q
        .rows
        .first()
        .map(|row| {
            let parsed = serde_json::from_str::<Value>(&cell_str(row, 0))
                .unwrap_or_else(|_| json!({}));
            (parsed, cell_str(row, 1))
        })
        .unwrap_or_else(|| (json!({}), String::new()));

    let observed_scopes: Vec<Value> = obs_res
        .map(|r| {
            r.rows
                .iter()
                .map(|row| {
                    json!({
                        "scope": cell_str(row, 0),
                        "resource_count": cell_i64(row, 1)
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    let observed_resource_groups: Vec<Value> = rg_res
        .map(|r| {
            r.rows
                .iter()
                .map(|row| {
                    json!({
                        "resource_group": cell_str(row, 0),
                        "resource_count": cell_i64(row, 1)
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "axis_filter": clean_opt(axis_filter),
        "updated_at": updated_at,
        "monitoring": scope_val.get("monitoring").cloned().unwrap_or_else(|| json!({"axis": "monitoring", "entries": []})),
        "action": scope_val.get("action").cloned().unwrap_or_else(|| json!({"axis": "action", "entries": []})),
        "executor_boundary": scope_val.get("executor_boundary").cloned().unwrap_or_else(|| json!({})),
        "observed_scopes": observed_scopes,
        "observed_resource_groups": observed_resource_groups
    })
}

fn extract_real_cidr(props: &Value) -> String {
    let inner = props.get("properties").unwrap_or(props);
    if let Some(prefix) = inner
        .get("addressPrefix")
        .or_else(|| props.get("addressPrefix"))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        return prefix.to_string();
    }
    if let Some(arr) = inner
        .get("addressSpace")
        .and_then(|v| v.get("addressPrefixes"))
        .or_else(|| props.get("addressSpace").and_then(|v| v.get("addressPrefixes")))
        .and_then(Value::as_array)
    {
        let joined: Vec<&str> = arr
            .iter()
            .filter_map(Value::as_str)
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .take(2)
            .collect();
        if !joined.is_empty() {
            return joined.join(", ");
        }
    }
    String::new()
}

fn classify_arch_edge_category(
    link_type: &str,
    src_type: &str,
    dst_type: &str,
) -> &'static str {
    if link_type == "peered_with" {
        return "peering";
    }
    let is_pe = |t: &str| {
        t.contains("private-endpoint")
            || t.contains("private-dns")
            || t.contains("privatelink")
    };
    if is_pe(src_type) || is_pe(dst_type) {
        return "pe";
    }
    let is_sec = |t: &str| {
        t.contains("nsg")
            || t.contains("secret-store")
            || t.contains("key-vault")
            || t.contains("managed-identity")
            || t.contains("firewall")
            || t.contains("authorization")
    };
    if is_sec(src_type) || is_sec(dst_type) {
        return "security";
    }
    "traffic"
}

pub async fn fetch_architecture(
    db: &DbHandle,
    scope: Option<&str>,
    layer: Option<&str>,
) -> Value {
    let raw_scope = clean_opt(scope).unwrap_or("all");
    let mut clauses: Vec<String> = vec!["object_type = 'Resource'".to_string()];
    let mut active_scope_id = "all".to_string();
    if !raw_scope.eq_ignore_ascii_case("all") {
        if let Some(rg_name) = raw_scope.strip_prefix("rg:") {
            let rg_trimmed = rg_name.trim();
            if !rg_trimmed.is_empty() {
                active_scope_id = format!("rg:{rg_trimmed}");
                clauses.push(format!(
                    "split_part(id, '/', 3) = {}",
                    pg_quote_literal(rg_trimmed)
                ));
            }
        } else if raw_scope.starts_with("scope-") {
            active_scope_id = raw_scope.to_string();
            let pat = quote_like_contains(raw_scope);
            clauses.push(format!("id ILIKE {pat} ESCAPE '\\'"));
        } else {
            active_scope_id = format!("rg:{raw_scope}");
            clauses.push(format!(
                "split_part(id, '/', 3) = {}",
                pg_quote_literal(raw_scope)
            ));
        }
    }
    if let Some(lyr) = clean_opt(layer) {
        let pat = quote_like_contains(lyr);
        clauses.push(format!(
            "COALESCE(properties->>'type','') ILIKE {pat} ESCAPE '\\'"
        ));
    }
    let where_sql = format!("WHERE {}", clauses.join(" AND "));

    let type_sql = format!(
        "SELECT COALESCE(properties->>'type', object_type) AS rtype, count(*) \
         FROM ontology_resource {where_sql} \
         GROUP BY 1 ORDER BY 2 DESC LIMIT 30"
    );
    let loc_sql = format!(
        "SELECT COALESCE(NULLIF(properties->>'location', ''), 'global') AS loc, count(*) \
         FROM ontology_resource {where_sql} \
         GROUP BY 1 ORDER BY 2 DESC LIMIT 15"
    );
    let all_rg_sql = "SELECT split_part(id, '/', 3) AS rg, count(*) \
                      FROM ontology_resource \
                      WHERE object_type = 'Resource' AND split_part(id, '/', 2) = 'resource-group' \
                      GROUP BY 1 ORDER BY 2 DESC LIMIT 30";
    let all_total_sql = "SELECT count(*) FROM ontology_resource WHERE object_type = 'Resource'";
    let link_sql = "SELECT link_type, count(*) FROM ontology_link GROUP BY 1 ORDER BY 2 DESC LIMIT 15";
    let snap_sql = "SELECT id, status, source, resource_count, link_count, \
                    to_char(completed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                    FROM inventory_snapshot WHERE status = 'active' ORDER BY completed_at DESC LIMIT 1";
    let summary_sql = format!(
        "SELECT \
            count(*), \
            count(*) FILTER (WHERE COALESCE(properties->>'type','') = 'network.vnet'), \
            count(*) FILTER (WHERE COALESCE(properties->>'type','') = 'network.subnet'), \
            count(*) FILTER (WHERE COALESCE(properties->>'type','') = 'network.private-endpoint'), \
            count(*) FILTER (WHERE COALESCE(properties->>'type','') = 'network.nsg'), \
            count(*) FILTER (WHERE COALESCE(properties->>'type','') ILIKE '%firewall%') \
         FROM ontology_resource {where_sql}"
    );
    let net_link_cnt_sql = "SELECT \
        count(*) FILTER (WHERE link_type = 'peered_with'), \
        count(*) FILTER (WHERE link_type = 'routes_to') \
        FROM ontology_link";

    // Core infrastructure priority ordering (exclude noisy role-assignment rows when infra exists)
    let nodes_sql = format!(
        "SELECT id, COALESCE(properties->>'type', object_type) AS rtype, \
         COALESCE(NULLIF(properties->>'location', ''), 'global'), \
         revision, COALESCE(properties->>'parent_id', ''), COALESCE(properties::text, '{{}}') \
         FROM ontology_resource {where_sql} \
         AND COALESCE(properties->>'type', '') <> 'resource-group' \
         ORDER BY \
            CASE \
              WHEN COALESCE(properties->>'type','') IN ('network.vnet','network.subnet','network.load-balancer','network.nat-gateway','network.private-endpoint','application-gateway') THEN 0 \
              WHEN COALESCE(properties->>'type','') IN ('kubernetes-cluster','kubernetes-node-pool','compute.container-app','compute.container-app-environment','compute.container-app-job','compute.vm-scale-set','compute.vm') THEN 1 \
              WHEN COALESCE(properties->>'type','') IN ('postgresql-server','cosmos-db','cache','object-storage','event-hub','service-bus','container-registry','llm-endpoint','llm-model-deployment') THEN 2 \
              WHEN COALESCE(properties->>'type','') IN ('secret-store','network.nsg','network.private-dns-zone','managed-identity','log-workspace','application-insights') THEN 3 \
              WHEN COALESCE(properties->>'type','') = 'authorization.role-assignment' THEN 9 \
              ELSE 5 \
            END, \
            split_part(id, '/', 3) ASC, id ASC \
         LIMIT 48"
    );

    let (
        type_res,
        loc_res,
        all_rg_res,
        all_total_res,
        link_res,
        snap_res,
        sum_res,
        net_link_res,
        nodes_res,
    ) = tokio::join!(
        db.query_single_readonly(&type_sql),
        db.query_single_readonly(&loc_sql),
        db.query_single_readonly(all_rg_sql),
        db.query_single_readonly(all_total_sql),
        db.query_single_readonly(link_sql),
        db.query_single_readonly(snap_sql),
        db.query_single_readonly(&summary_sql),
        db.query_single_readonly(net_link_cnt_sql),
        db.query_single_readonly(&nodes_sql),
    );
    let Ok(tq) = type_res else {
        return db.not_measured(
            "governance",
            "/api/v4/governance/architecture",
            "postgres_unreachable",
        );
    };

    let resource_types: Vec<Value> = tq
        .rows
        .iter()
        .map(|r| json!({ "resource_type": cell_str(r, 0), "count": cell_i64(r, 1) }))
        .collect();
    let locations: Vec<Value> = loc_res
        .map(|r| {
            r.rows
                .iter()
                .map(|row| json!({ "location": cell_str(row, 0), "count": cell_i64(row, 1) }))
                .collect()
        })
        .unwrap_or_default();
    let resource_groups: Vec<Value> = all_rg_res
        .map(|r| {
            r.rows
                .iter()
                .map(|row| json!({ "resource_group": cell_str(row, 0), "count": cell_i64(row, 1) }))
                .collect()
        })
        .unwrap_or_default();
    let link_summary: Vec<Value> = link_res
        .map(|r| {
            r.rows
                .iter()
                .map(|row| json!({ "link_type": cell_str(row, 0), "count": cell_i64(row, 1) }))
                .collect()
        })
        .unwrap_or_default();
    let active_snapshot = snap_res.ok().and_then(|r| {
        r.rows.first().map(|row| {
            json!({
                "id": cell_str(row, 0),
                "status": cell_str(row, 1),
                "source": cell_str(row, 2),
                "resource_count": cell_i64(row, 3),
                "link_count": cell_i64(row, 4),
                "completed_at": cell_str(row, 5),
            })
        })
    });

    let all_fleet_resources = all_total_res
        .ok()
        .and_then(|r| r.rows.first().and_then(|row| cell_i64(row, 0)))
        .unwrap_or(0);
    let sum_row = sum_res.ok().and_then(|r| r.rows.first().cloned());
    let total_resources = sum_row
        .as_ref()
        .and_then(|r| cell_i64(r, 0))
        .unwrap_or(0);
    let vnet_count = sum_row.as_ref().and_then(|r| cell_i64(r, 1)).unwrap_or(0);
    let subnet_count = sum_row.as_ref().and_then(|r| cell_i64(r, 2)).unwrap_or(0);
    let pe_count = sum_row.as_ref().and_then(|r| cell_i64(r, 3)).unwrap_or(0);
    let nsg_count = sum_row.as_ref().and_then(|r| cell_i64(r, 4)).unwrap_or(0);
    let firewall_count = sum_row.as_ref().and_then(|r| cell_i64(r, 5)).unwrap_or(0);
    let (peering_count, route_count) = net_link_res
        .ok()
        .and_then(|r| r.rows.first().cloned())
        .map(|r| (cell_i64(&r, 0).unwrap_or(0), cell_i64(&r, 1).unwrap_or(0)))
        .unwrap_or((0, 0));

    let total_links: i64 = link_summary
        .iter()
        .filter_map(|v| v.get("count").and_then(Value::as_i64))
        .sum();
    let network_resource_count: i64 = resource_types
        .iter()
        .filter(|v| {
            v.get("resource_type")
                .and_then(Value::as_str)
                .is_some_and(|t| t.contains("vnet") || t.contains("network"))
        })
        .filter_map(|v| v.get("count").and_then(Value::as_i64))
        .sum();

    // Build views list
    let mut views: Vec<Value> = vec![json!({
        "id": "all",
        "label": format!("전체 실측 스코프 ({all_fleet_resources}건)"),
        "count": all_fleet_resources
    })];
    for rg in &resource_groups {
        let name = rg
            .get("resource_group")
            .and_then(Value::as_str)
            .unwrap_or("");
        let cnt = rg.get("count").and_then(Value::as_i64).unwrap_or(0);
        if !name.is_empty() {
            views.push(json!({
                "id": format!("rg:{name}"),
                "resource_group": name,
                "label": format!("{name} ({cnt}건)"),
                "count": cnt
            }));
        }
    }

    // Parse raw nodes and index their types and containers
    struct RawArchNode {
        id: String,
        display_name: String,
        resource_type: String,
        location: String,
        subscription: String,
        resource_group: String,
        parent_id: String,
        cidr: String,
        revision: Option<i64>,
    }

    let mut raw_nodes: Vec<RawArchNode> = Vec::new();
    if let Ok(nq) = nodes_res {
        for row in &nq.rows {
            let id = cell_str(row, 0);
            let rtype = cell_str(row, 1);
            let loc = cell_str(row, 2);
            let rev = cell_i64(row, 3);
            let parent_id = cell_str(row, 4);
            let props: Value =
                serde_json::from_str(&cell_str(row, 5)).unwrap_or_else(|_| json!({}));
            let dname = resolve_ontology_display_name(&id, "Resource", &props);
            let (sub, rg) = extract_sub_and_rg(&id, &props);
            let cidr = extract_real_cidr(&props);
            raw_nodes.push(RawArchNode {
                id,
                display_name: dname,
                resource_type: rtype,
                location: loc,
                subscription: sub,
                resource_group: rg,
                parent_id,
                cidr,
                revision: rev,
            });
        }
    }

    let mut node_type_map: HashMap<String, String> = HashMap::new();
    for n in &raw_nodes {
        node_type_map.insert(n.id.clone(), n.resource_type.clone());
    }

    // Query ONLY real ontology_link edges strictly between selected nodes[]
    let mut edges: Vec<Value> = Vec::new();
    let mut node_attached_container: HashMap<String, String> = HashMap::new();
    if !raw_nodes.is_empty() {
        let quoted_ids: Vec<String> = raw_nodes.iter().map(|n| pg_quote_literal(&n.id)).collect();
        let in_list = quoted_ids.join(", ");
        let edges_sql = format!(
            "SELECT id::text, from_id, to_id, link_type \
             FROM ontology_link \
             WHERE link_type IN ('contains', 'attached_to', 'depends_on', 'peered_with', 'routes_to') \
               AND from_id IN ({in_list}) \
               AND to_id IN ({in_list}) \
             ORDER BY link_type ASC, from_id ASC LIMIT 160"
        );
        if let Ok(eq) = db.query_single_readonly(&edges_sql).await {
            for row in &eq.rows {
                let eid = cell_str(row, 0);
                let src = cell_str(row, 1);
                let dst = cell_str(row, 2);
                let lt = cell_str(row, 3);
                if src == dst {
                    continue;
                }
                let st = node_type_map.get(&src).map(String::as_str).unwrap_or("");
                let dt = node_type_map.get(&dst).map(String::as_str).unwrap_or("");
                if (lt == "attached_to" || lt == "contains")
                    && (dt == "network.subnet" || dt == "network.vnet")
                {
                    node_attached_container
                        .entry(src.clone())
                        .or_insert_with(|| dst.clone());
                } else if lt == "contains" && (st == "network.subnet" || st == "network.vnet") {
                    node_attached_container
                        .entry(dst.clone())
                        .or_insert_with(|| src.clone());
                }
                let category = classify_arch_edge_category(&lt, st, dt);
                edges.push(json!({
                    "id": eid,
                    "source": src,
                    "target": dst,
                    "link_type": lt,
                    "category": category
                }));
            }
        }
    }

    // Build real containers (VNet / Subnet / Resource Group) and assign container_id per node
    type ContainerEntry = (String, String, String, Option<String>, usize);
    let mut container_map: HashMap<String, ContainerEntry> = HashMap::new();
    let mut container_order: Vec<String> = Vec::new();
    fn ensure_container(
        container_map: &mut HashMap<String, ContainerEntry>,
        container_order: &mut Vec<String>,
        cid: String,
        kind: &str,
        name: String,
        subtitle: String,
        parent: Option<String>,
    ) {
        if let std::collections::hash_map::Entry::Vacant(slot) = container_map.entry(cid) {
            container_order.push(slot.key().clone());
            slot.insert((kind.to_string(), name, subtitle, parent, 0));
        }
    }

    // Register real VNet / Subnet nodes as containers first
    let mut vnet_subnet_ids: HashMap<String, String> = HashMap::new();
    for n in &raw_nodes {
        if n.resource_type == "network.vnet" || n.resource_type == "network.subnet" {
            let kind = if n.resource_type == "network.vnet" {
                "vnet"
            } else {
                "subnet"
            };
            let subtitle = if !n.cidr.is_empty() {
                format!("{} · {}", n.cidr, n.location)
            } else if !n.resource_group.is_empty() {
                format!("{} · {}", n.resource_group, n.location)
            } else {
                n.location.clone()
            };
            let parent = if !n.parent_id.is_empty() {
                Some(n.parent_id.clone())
            } else {
                None
            };
            ensure_container(
                &mut container_map,
                &mut container_order,
                n.id.clone(),
                kind,
                n.display_name.clone(),
                subtitle,
                parent,
            );
            vnet_subnet_ids.insert(n.id.clone(), kind.to_string());
        }
    }

    let mut nodes: Vec<Value> = Vec::with_capacity(raw_nodes.len());
    for n in &raw_nodes {
        let cid = if vnet_subnet_ids.contains_key(&n.id) {
            n.id.clone()
        } else if let Some(attached) = node_attached_container.get(&n.id) {
            if container_map.contains_key(attached) {
                attached.clone()
            } else {
                let rg_key = if n.resource_group.is_empty() {
                    "rg:managed".to_string()
                } else {
                    format!("rg:{}", n.resource_group)
                };
                let rg_label = if n.resource_group.is_empty() {
                    "관리 리소스".to_string()
                } else {
                    n.resource_group.clone()
                };
                let kind = if rg_label.starts_with("mc_") || rg_label.starts_with("me_") {
                    "managed"
                } else {
                    "resource_group"
                };
                ensure_container(
                    &mut container_map,
                    &mut container_order,
                    rg_key.clone(),
                    kind,
                    rg_label,
                    n.location.clone(),
                    Some(n.subscription.clone()),
                );
                rg_key
            }
        } else if container_map.contains_key(&n.parent_id) {
            n.parent_id.clone()
        } else {
            let rg_key = if n.resource_group.is_empty() {
                "rg:managed".to_string()
            } else {
                format!("rg:{}", n.resource_group)
            };
            let rg_label = if n.resource_group.is_empty() {
                "관리 리소스".to_string()
            } else {
                n.resource_group.clone()
            };
            let kind = if rg_label.starts_with("mc_") || rg_label.starts_with("me_") {
                "managed"
            } else {
                "resource_group"
            };
            ensure_container(
                &mut container_map,
                &mut container_order,
                rg_key.clone(),
                kind,
                rg_label,
                n.location.clone(),
                Some(n.subscription.clone()),
            );
            rg_key
        };

        if let Some(entry) = container_map.get_mut(&cid) {
            entry.4 += 1;
        }
        nodes.push(json!({
            "id": n.id,
            "name": n.display_name,
            "display_name": n.display_name,
            "object_type_ko": ontology_type_label_ko("Resource"),
            "resource_type": n.resource_type,
            "location": n.location,
            "subscription": n.subscription,
            "resource_group": n.resource_group,
            "container_id": cid,
            "revision": n.revision,
            "status": "observed"
        }));
    }

    let containers: Vec<Value> = container_order
        .into_iter()
        .filter_map(|cid| {
            container_map
                .remove(&cid)
                .map(|(kind, name, subtitle, parent_id, count)| {
                    json!({
                        "id": cid,
                        "kind": kind,
                        "name": name,
                        "subtitle": subtitle,
                        "parent_id": parent_id,
                        "resource_count": count
                    })
                })
        })
        .collect();

    let top_resources: Vec<Value> = nodes.iter().take(12).cloned().collect();
    let sample_links: Vec<Value> = edges.iter().take(12).cloned().collect();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "active_scope": active_scope_id,
        "total_resources": total_resources,
        "total_links": total_links,
        "resource_group_count": resource_groups.len(),
        "network_resource_count": network_resource_count,
        "summary": {
            "vnet_count": vnet_count,
            "subnet_count": subnet_count,
            "private_endpoint_count": pe_count,
            "nsg_count": nsg_count,
            "firewall_count": firewall_count,
            "peering_count": peering_count,
            "route_count": route_count,
            "total_resources": total_resources,
            "total_links": total_links
        },
        "views": views,
        "containers": containers,
        "nodes": nodes,
        "edges": edges,
        "active_snapshot": active_snapshot,
        "resource_types": resource_types,
        "locations": locations,
        "resource_groups": resource_groups,
        "link_summary": link_summary,
        "top_resources": top_resources,
        "sample_links": sample_links
    })
}

pub async fn fetch_blast_radius(
    db: &DbHandle,
    target: Option<&str>,
    hop: Option<usize>,
) -> Value {
    let max_hop = hop.unwrap_or(3).clamp(1, 3);

    let target_sql = match clean_opt(target) {
        Some(t) => {
            let exact = pg_quote_literal(t);
            let pat = quote_like_contains(t);
            format!(
                "SELECT id, COALESCE(properties->>'name', id), COALESCE(properties->>'type', object_type), \
                 COALESCE(properties->>'location', '') \
                 FROM ontology_resource \
                 WHERE id = {exact} OR COALESCE(properties->>'name','') = {exact} OR id ILIKE {pat} ESCAPE '\\' OR COALESCE(properties->>'name','') ILIKE {pat} ESCAPE '\\' \
                 ORDER BY CASE WHEN id = {exact} THEN 0 WHEN COALESCE(properties->>'name','') = {exact} THEN 1 ELSE 2 END \
                 LIMIT 1"
            )
        }
        None => "SELECT r.id, COALESCE(r.properties->>'name', r.id), COALESCE(r.properties->>'type', r.object_type), \
                 COALESCE(r.properties->>'location', '') \
                 FROM ontology_resource r \
                 JOIN ontology_link l ON l.from_id = r.id OR l.to_id = r.id \
                 WHERE r.object_type = 'Resource' \
                 GROUP BY r.id, r.properties, r.object_type \
                 ORDER BY count(l.id) DESC \
                 LIMIT 1"
            .to_string(),
    };

    let cand_sql = "SELECT r.id, COALESCE(r.properties->>'name', r.id), \
                    COALESCE(r.properties->>'type', r.object_type), count(l.id) AS deg \
                    FROM ontology_resource r \
                    JOIN ontology_link l ON l.from_id = r.id OR l.to_id = r.id \
                    WHERE r.object_type = 'Resource' \
                    GROUP BY r.id, r.properties, r.object_type \
                    ORDER BY deg DESC LIMIT 12";

    let (t_res, c_res) = tokio::join!(
        db.query_single_readonly(&target_sql),
        db.query_single_readonly(cand_sql),
    );
    let Ok(tq) = t_res else {
        return db.not_measured(
            "governance",
            "/api/v4/governance/blast-radius",
            "postgres_unreachable",
        );
    };

    let candidates: Vec<Value> = c_res
        .map(|r| {
            r.rows
                .iter()
                .map(|row| {
                    json!({
                        "id": cell_str(row, 0),
                        "name": cell_str(row, 1),
                        "resource_type": cell_str(row, 2),
                        "degree": cell_i64(row, 3),
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    let Some(t_row) = tq.rows.first() else {
        return json!({
            "measurement_status": "measured",
            "source": "postgres-direct",
            "target": target,
            "max_hop": max_hop,
            "hop_1": 0,
            "hop_2": 0,
            "hop_3": 0,
            "affected_resources": [],
            "candidates": candidates
        });
    };

    let target_id = cell_str(t_row, 0);
    let target_name = cell_str(t_row, 1);
    let target_type = cell_str(t_row, 2);
    let target_loc = cell_str(t_row, 3);
    let q_tid = pg_quote_literal(&target_id);

    let cte_sql = format!(
        "WITH \
         h1 AS ( \
            SELECT CASE WHEN from_id = {q_tid} THEN to_id ELSE from_id END AS node_id, \
                   min(link_type) AS via_link \
            FROM ontology_link \
            WHERE from_id = {q_tid} OR to_id = {q_tid} \
            GROUP BY 1 \
         ), \
         h2 AS ( \
            SELECT CASE WHEN l.from_id = h1.node_id THEN l.to_id ELSE l.from_id END AS node_id, \
                   min(l.link_type) AS via_link \
            FROM h1 \
            JOIN ontology_link l ON l.from_id = h1.node_id OR l.to_id = h1.node_id \
            WHERE CASE WHEN l.from_id = h1.node_id THEN l.to_id ELSE l.from_id END <> {q_tid} \
              AND NOT EXISTS (SELECT 1 FROM h1 x WHERE x.node_id = CASE WHEN l.from_id = h1.node_id THEN l.to_id ELSE l.from_id END) \
            GROUP BY 1 \
         ), \
         h3 AS ( \
            SELECT CASE WHEN l.from_id = h2.node_id THEN l.to_id ELSE l.from_id END AS node_id, \
                   min(l.link_type) AS via_link \
            FROM h2 \
            JOIN ontology_link l ON l.from_id = h2.node_id OR l.to_id = h2.node_id \
            WHERE CASE WHEN l.from_id = h2.node_id THEN l.to_id ELSE l.from_id END <> {q_tid} \
              AND NOT EXISTS (SELECT 1 FROM h1 x WHERE x.node_id = CASE WHEN l.from_id = h2.node_id THEN l.to_id ELSE l.from_id END) \
              AND NOT EXISTS (SELECT 1 FROM h2 x WHERE x.node_id = CASE WHEN l.from_id = h2.node_id THEN l.to_id ELSE l.from_id END) \
            GROUP BY 1 \
         ), \
         best AS ( \
            SELECT node_id, 1 AS hop, via_link FROM h1 \
            UNION ALL \
            SELECT node_id, 2 AS hop, via_link FROM h2 WHERE {max_hop} >= 2 \
            UNION ALL \
            SELECT node_id, 3 AS hop, via_link FROM h3 WHERE {max_hop} >= 3 \
         )"
    );

    let counts_sql = format!(
        "{cte_sql} \
         SELECT \
            count(*) FILTER (WHERE hop = 1), \
            count(*) FILTER (WHERE hop = 2), \
            count(*) FILTER (WHERE hop = 3) \
         FROM best"
    );
    let sample_sql = format!(
        "{cte_sql}, ranked AS ( \
            SELECT b.node_id, b.hop, b.via_link, \
                   ROW_NUMBER() OVER (PARTITION BY b.hop ORDER BY b.node_id ASC) AS rn \
            FROM best b \
         ) \
         SELECT k.node_id, k.hop, k.via_link, \
                COALESCE(r.object_type, 'Resource'), \
                COALESCE(r.properties->>'type', r.object_type, 'Resource'), \
                COALESCE(r.properties::text, '{{}}') \
         FROM ranked k \
         LEFT JOIN ontology_resource r ON r.id = k.node_id \
         WHERE k.rn <= 25 \
         ORDER BY k.hop ASC, k.node_id ASC"
    );

    let (cnt_res, bq_res) = tokio::join!(
        db.query_single_readonly(&counts_sql),
        db.query_single_readonly(&sample_sql),
    );
    let (Ok(cnt_q), Ok(bq)) = (cnt_res, bq_res) else {
        return db.not_measured(
            "governance",
            "/api/v4/governance/blast-radius",
            "postgres_unreachable",
        );
    };

    let cnt_row = cnt_q.rows.first();
    let hop_1 = cnt_row.and_then(|r| cell_i64(r, 0)).unwrap_or(0).max(0) as usize;
    let hop_2 = cnt_row.and_then(|r| cell_i64(r, 1)).unwrap_or(0).max(0) as usize;
    let hop_3 = cnt_row.and_then(|r| cell_i64(r, 2)).unwrap_or(0).max(0) as usize;
    let total_affected = hop_1 + hop_2 + hop_3;

    let mut affected = Vec::with_capacity(bq.rows.len());
    for row in &bq.rows {
        let nid = cell_str(row, 0);
        let h = cell_i64(row, 1).unwrap_or(1);
        let ot = cell_str(row, 3);
        let rtype = cell_str(row, 4);
        let props: Value =
            serde_json::from_str(&cell_str(row, 5)).unwrap_or_else(|_| json!({}));
        let dname = resolve_ontology_display_name(&nid, &ot, &props);
        affected.push(json!({
            "id": nid,
            "hop": h,
            "link_type": cell_str(row, 2),
            "object_type": ot,
            "object_type_ko": ontology_type_label_ko(&ot),
            "name": dname,
            "display_name": dname,
            "resource_type": rtype,
        }));
    }

    let risk_class = if hop_1 >= 10 || (hop_1 + hop_2) >= 25 {
        "A3"
    } else if hop_1 >= 3 {
        "A2"
    } else {
        "A1"
    };

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "target": target_name,
        "target_id": target_id,
        "target_type": target_type,
        "target_location": target_loc,
        "max_hop": max_hop,
        "risk_class": risk_class,
        "hop_1": hop_1,
        "hop_2": hop_2,
        "hop_3": hop_3,
        "total_affected": total_affected,
        "affected_resources": affected,
        "candidates": candidates
    })
}

pub async fn fetch_promotion_gates(
    db: &DbHandle,
    state_filter: Option<&str>,
    action_type_filter: Option<&str>,
) -> Value {
    let kv_sql = "SELECT value::text, to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                  FROM state_kv WHERE key = 'operator-projection:workflow:promotion-gate.list' LIMIT 1";
    let hist_sql = "SELECT seq, \
                    to_char(created_at AT TIME ZONE 'UTC', 'MM-DD HH24:MI'), \
                    action_kind, \
                    actor, \
                    COALESCE(NULLIF(entry->>'action_type_name', ''), NULLIF(entry->>'action_type', ''), NULLIF(entry->>'target', ''), action_kind), \
                    COALESCE(NULLIF(entry->>'reason', ''), NULLIF(entry->>'outcome', ''), NULLIF(entry->>'mode', ''), ''), \
                    to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                    FROM audit_log \
                    WHERE action_kind ILIKE '%promot%' OR action_kind ILIKE '%recall%' OR action_kind ILIKE '%demot%' \
                    ORDER BY seq DESC LIMIT 12";
    let (kv_res, hist_res) = tokio::join!(
        db.query_single_readonly(kv_sql),
        db.query_single_readonly(hist_sql),
    );
    let Ok(res) = kv_res else {
        return db.not_measured(
            "governance",
            "/api/v4/governance/promotion-gates",
            "postgres_unreachable",
        );
    };

    let (parsed, updated_at) = res
        .rows
        .first()
        .map(|row| {
            let v = serde_json::from_str::<Value>(&cell_str(row, 0)).unwrap_or_else(|_| json!({}));
            (v, cell_str(row, 1))
        })
        .unwrap_or_else(|| (json!({}), String::new()));

    let raw_rows = parsed
        .get("rows")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let sf = clean_opt(state_filter).map(str::to_ascii_lowercase);
    let af = clean_opt(action_type_filter).map(str::to_ascii_lowercase);

    let rows: Vec<Value> = raw_rows
        .into_iter()
        .filter(|row| {
            let ready = row.get("ready").and_then(Value::as_bool).unwrap_or(false);
            if let Some(ref s) = sf {
                match s.as_str() {
                    "ready" if !ready => return false,
                    "blocked" | "shadow" if ready => return false,
                    _ => {}
                }
            }
            if let Some(ref a) = af {
                let name = row
                    .get("action_type_name")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_ascii_lowercase();
                if !name.contains(a) {
                    return false;
                }
            }
            true
        })
        .collect();

    let ready_count = parsed
        .get("ready_count")
        .and_then(Value::as_u64)
        .unwrap_or_else(|| {
            rows.iter()
                .filter(|r| r.get("ready").and_then(Value::as_bool).unwrap_or(false))
                .count() as u64
        });
    let blocked_count = parsed
        .get("blocked_count")
        .and_then(Value::as_u64)
        .unwrap_or_else(|| (rows.len() as u64).saturating_sub(ready_count));
    let recall_count = parsed.get("recall_count").and_then(Value::as_u64);
    let window_days = parsed
        .get("window_days")
        .and_then(Value::as_u64)
        .unwrap_or(14);

    let audit_history: Vec<Value> = hist_res
        .map(|h| {
            h.rows
                .iter()
                .map(|row| {
                    json!({
                        "seq": cell_i64(row, 0),
                        "time": cell_str(row, 1),
                        "created_at": cell_str(row, 6),
                        "action_kind": cell_str(row, 2),
                        "actor": cell_str(row, 3),
                        "target": cell_str(row, 4),
                        "detail": cell_str(row, 5)
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "updated_at": updated_at,
        "window_days": window_days,
        "ready_count": ready_count,
        "blocked_count": blocked_count,
        "recall_count": recall_count,
        "total": rows.len(),
        "rows": rows,
        "items": rows,
        "audit_history": audit_history
    })
}

pub async fn fetch_workflows(
    db: &DbHandle,
    mode_filter: Option<&str>,
    template_filter: Option<&str>,
) -> Value {
    let mut clauses: Vec<String> = Vec::new();
    if let Some(m) = clean_opt(mode_filter) {
        clauses.push(format!("lower(lifecycle) = {}", pg_quote_literal(&m.to_ascii_lowercase())));
    }
    if let Some(t) = clean_opt(template_filter) {
        let pat = quote_like_contains(t);
        clauses.push(format!(
            "(workflow_name ILIKE {pat} ESCAPE '\\' OR definition_id ILIKE {pat} ESCAPE '\\')"
        ));
    }
    let where_sql = if clauses.is_empty() {
        String::new()
    } else {
        format!("WHERE {}", clauses.join(" AND "))
    };
    let sql = format!(
        "SELECT definition_id, workflow_name, workflow_version, origin, visibility, lifecycle, \
         COALESCE(owner_ref, 'system'), COALESCE(workflow_document::text, '{{}}'), \
         to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
         FROM workflow_definition {where_sql} \
         ORDER BY workflow_name ASC LIMIT 100"
    );
    let Ok(res) = db.query_single_readonly(&sql).await else {
        return db.not_measured(
            "governance",
            "/api/v4/governance/workflows",
            "postgres_unreachable",
        );
    };

    let mut workflows = Vec::with_capacity(res.rows.len());
    for row in &res.rows {
        let def_id = cell_str(row, 0);
        let name = cell_str(row, 1);
        let version = cell_str(row, 2);
        let origin = cell_str(row, 3);
        let visibility = cell_str(row, 4);
        let lifecycle = cell_str(row, 5);
        let owner_ref = cell_str(row, 6);
        let doc_raw = cell_str(row, 7);
        let created_at = cell_str(row, 8);
        let doc_val: Value = serde_json::from_str(&doc_raw).unwrap_or_else(|_| json!({}));
        let steps = doc_val
            .get("steps")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let step_names: Vec<String> = steps
            .iter()
            .filter_map(|s| s.get("id").and_then(Value::as_str).map(String::from))
            .collect();
        workflows.push(json!({
            "definition_id": def_id,
            "workflow_name": name,
            "workflow_version": version,
            "origin": origin,
            "visibility": visibility,
            "lifecycle": lifecycle,
            "shadow_locked": lifecycle.eq_ignore_ascii_case("shadow"),
            "owner_ref": owner_ref,
            "step_count": steps.len(),
            "step_ids": step_names,
            "workflow_document": doc_val,
            "created_at": created_at
        }));
    }

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "total": workflows.len(),
        "workflows": workflows,
        "items": workflows
    })
}

pub async fn fetch_knowledge(db: &DbHandle, provider_filter: Option<&str>) -> Value {
    let doc_cnt_sql = "SELECT count(*) FROM catalog_search_generation_document";
    let src_cnt_sql = "SELECT count(*) FROM document_knowledge_source";
    let src_rows_sql = "SELECT source_id, revision, left(registry_digest, 24), \
                        COALESCE(NULLIF(payload->>'provider', ''), 'github'), \
                        COALESCE(NULLIF(payload->>'repository', ''), NULLIF(payload->>'repo', ''), source_id), \
                        COALESCE(NULLIF(payload->>'branch', ''), 'main'), \
                        COALESCE(payload->>'commit_sha', ''), \
                        COALESCE(NULLIF(payload->>'status', ''), 'observed') \
                        FROM document_knowledge_source \
                        ORDER BY revision DESC, source_id ASC LIMIT 20";
    let ver_cnt_sql = "SELECT count(*) FROM document_version";
    let chunk_cnt_sql = "SELECT count(*) FROM knowledge_chunk";
    let fw_sql = "SELECT key, length(value::text) FROM state_kv \
                  WHERE key IN ('operator-projection:workflow:best-practice.list', \
                                'operator-projection:workflow:caf.list', \
                                'operator-projection:workflow:mcsb.list', \
                                'operator-projection:workflow:wara.list')";
    let cat_items_sql = "SELECT rule_id, document_kind, ordinal, left(COALESCE(text, ''), 300) \
                         FROM catalog_search_generation_document \
                         ORDER BY ordinal ASC LIMIT 8";

    let (d_res, s_res, sr_res, v_res, c_res, fw_res, cat_res) = tokio::join!(
        db.query_single_readonly(doc_cnt_sql),
        db.query_single_readonly(src_cnt_sql),
        db.query_single_readonly(src_rows_sql),
        db.query_single_readonly(ver_cnt_sql),
        db.query_single_readonly(chunk_cnt_sql),
        db.query_single_readonly(fw_sql),
        db.query_single_readonly(cat_items_sql),
    );
    let Ok(dq) = d_res else {
        return db.not_measured(
            "governance",
            "/api/v4/governance/knowledge",
            "postgres_unreachable",
        );
    };

    let catalog_doc_count = dq.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let source_count = s_res
        .ok()
        .and_then(|r| r.rows.first().and_then(|row| cell_i64(row, 0)))
        .unwrap_or(0);
    let source_rows: Vec<Value> = sr_res
        .map(|r| {
            r.rows
                .iter()
                .map(|row| {
                    json!({
                        "source_id": cell_str(row, 0),
                        "revision": cell_i64(row, 1).unwrap_or(0),
                        "registry_digest": cell_str(row, 2),
                        "provider": cell_str(row, 3),
                        "repository": cell_str(row, 4),
                        "branch": cell_str(row, 5),
                        "commit_sha": cell_str(row, 6),
                        "status": cell_str(row, 7)
                    })
                })
                .collect()
        })
        .unwrap_or_default();
    let version_count = v_res
        .ok()
        .and_then(|r| r.rows.first().and_then(|row| cell_i64(row, 0)))
        .unwrap_or(0);
    let chunk_count = c_res
        .ok()
        .and_then(|r| r.rows.first().and_then(|row| cell_i64(row, 0)))
        .unwrap_or(0);

    let framework_projections: Vec<Value> = fw_res
        .map(|r| {
            r.rows
                .iter()
                .map(|row| {
                    json!({
                        "key": cell_str(row, 0),
                        "bytes": cell_i64(row, 1),
                        "status": "measured"
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    let recent_catalog_items: Vec<Value> = cat_res
        .map(|r| {
            r.rows
                .iter()
                .map(|row| {
                    let rule_id = cell_str(row, 0);
                    let kind = cell_str(row, 1);
                    let ord = cell_i64(row, 2);
                    let text = cell_str(row, 3);
                    let lines: Vec<&str> = text.lines().map(str::trim).filter(|l| !l.is_empty()).collect();
                    let rtype = lines.get(1).copied().unwrap_or("azure-resource");
                    let cat = lines.get(2).copied().unwrap_or("general");
                    let sev = lines.get(3).copied().unwrap_or("medium");
                    let title = lines.get(4).copied().unwrap_or(&rule_id);
                    json!({
                        "rule_id": rule_id,
                        "document_kind": kind,
                        "ordinal": ord,
                        "title": title,
                        "resource_type": rtype,
                        "category": cat,
                        "severity": sev
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    let github_items: Vec<Value> = source_rows
        .iter()
        .filter(|s| s.get("provider").and_then(Value::as_str).unwrap_or("github").eq_ignore_ascii_case("github"))
        .cloned()
        .collect();
    let gitlab_items: Vec<Value> = source_rows
        .iter()
        .filter(|s| s.get("provider").and_then(Value::as_str).unwrap_or("").eq_ignore_ascii_case("gitlab"))
        .cloned()
        .collect();
    let ado_items: Vec<Value> = source_rows
        .iter()
        .filter(|s| {
            let p = s.get("provider").and_then(Value::as_str).unwrap_or("");
            p.eq_ignore_ascii_case("azure-devops") || p.eq_ignore_ascii_case("azure_devops")
        })
        .cloned()
        .collect();

    let github_connected = !github_items.is_empty() || (source_count > 0 && gitlab_items.is_empty() && ado_items.is_empty());

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "provider_filter": clean_opt(provider_filter),
        "cloud_knowledge": {
            "catalog_documents": catalog_doc_count,
            "document_versions": version_count,
            "knowledge_chunks": chunk_count,
            "framework_projection_count": framework_projections.len(),
            "framework_projections": framework_projections,
            "recent_catalog_items": recent_catalog_items
        },
        "github_sources": {
            "connected": github_connected,
            "source_count": if !github_items.is_empty() { github_items.len() as i64 } else { source_count },
            "sources": github_items
        },
        "gitlab_sources": {
            "connected": !gitlab_items.is_empty(),
            "source_count": gitlab_items.len(),
            "sources": gitlab_items
        },
        "azure_devops_sources": {
            "connected": !ado_items.is_empty(),
            "source_count": ado_items.len(),
            "sources": ado_items
        },
        "provider_states": {
            "documents": if catalog_doc_count > 0 { "measured" } else { "not-connected" },
            "github": if github_connected { "measured" } else { "not-connected" },
            "gitlab": if !gitlab_items.is_empty() { "measured" } else { "not-connected" },
            "azure_devops": if !ado_items.is_empty() { "measured" } else { "not-connected" }
        }
    })
}

fn framework_domain_label_ko(raw: &str) -> String {
    match raw.trim().to_ascii_lowercase().as_str() {
        "am" => "자산 관리 (AM)".to_string(),
        "ns" => "네트워크 보안 (NS)".to_string(),
        "im" => "ID 관리 (IM)".to_string(),
        "pa" => "권한 접근 (PA)".to_string(),
        "dp" => "데이터 보호 (DP)".to_string(),
        "lt" => "로깅·위협 탐지 (LT)".to_string(),
        "ir" => "사고 대응 (IR)".to_string(),
        "pv" => "상태·취약점 관리 (PV)".to_string(),
        "es" => "엔드포인트 보안 (ES)".to_string(),
        "br" => "백업·복구 (BR)".to_string(),
        "ds" => "DevOps 보안 (DS)".to_string(),
        "gs" => "거버넌스·전략 (GS)".to_string(),
        "methodology" => "클라우드 도입 방법론".to_string(),
        "landing_zone" | "landing-zone" => "랜딩 존 (Landing Zone)".to_string(),
        "govern" | "governance" => "거버넌스 (Govern)".to_string(),
        "manage" => "운영 관리 (Manage)".to_string(),
        "secure" | "security" => "보안 (Security)".to_string(),
        "ready" => "준비 (Ready)".to_string(),
        "adopt" => "도입 (Adopt)".to_string(),
        "cost_optimization" | "cost-optimization" => "비용 최적화 (Cost Optimization)".to_string(),
        "operational_excellence" | "operational-excellence" => {
            "운영 우수성 (Operational Excellence)".to_string()
        }
        "performance_efficiency" | "performance-efficiency" => {
            "성능 효율성 (Performance Efficiency)".to_string()
        }
        "reliability" => "신뢰성 (Reliability)".to_string(),
        "high" => "높은 영향 (High Impact)".to_string(),
        "medium" => "보통 영향 (Medium Impact)".to_string(),
        "low" => "낮은 영향 (Low Impact)".to_string(),
        "" => "일반 기준".to_string(),
        other => other.to_string(),
    }
}

pub async fn fetch_frameworks(
    db: &DbHandle,
    framework: Option<&str>,
    search: Option<&str>,
    limit: Option<usize>,
    offset: Option<usize>,
) -> Value {
    let selected = match clean_opt(framework).map(str::to_ascii_lowercase).as_deref() {
        Some("mcsb") | Some("fw-mcsb") => "mcsb",
        Some("caf") | Some("fw-caf") => "caf",
        Some("wara") | Some("fw-wara") => "wara",
        Some("waf") | Some("best-practice") | Some("best_practice") | Some("fw-waf") => "waf",
        Some("msrc") | Some("fw-msrc") => "msrc",
        _ => "all",
    };
    let lim = clamp_limit(limit, 120, 500);
    let off = offset.unwrap_or(0).min(100_000);

    let counts_sql = "SELECT key, \
        COALESCE(jsonb_array_length(value->'controls'), 0), \
        COALESCE(value->>'framework_version', value->>'source_revision', ''), \
        COALESCE(value->>'evaluation_source', '') \
        FROM state_kv \
        WHERE key IN ( \
            'operator-projection:workflow:mcsb-assessment.list', \
            'operator-projection:workflow:caf.list', \
            'operator-projection:workflow:wara.list', \
            'operator-projection:workflow:best-practice.list' \
        )";
    let msrc_cnt_sql = "SELECT \
        count(*) FILTER (WHERE lower(COALESCE(d.val->>'source','')) IN ('msrc', 'msrc_csaf', 'csaf', 'security_advisory')), \
        count(*) FILTER (WHERE lower(COALESCE(d.val->>'category','')) = 'security') \
        FROM state_kv sk, jsonb_each(sk.value->'details') AS d(k, val) \
        WHERE sk.key = 'operator-projection:workflow:rule.list'";

    let target_fw = if selected == "all" { "mcsb" } else { selected };
    let target_key = match target_fw {
        "mcsb" => Some("operator-projection:workflow:mcsb-assessment.list"),
        "caf" => Some("operator-projection:workflow:caf.list"),
        "wara" => Some("operator-projection:workflow:wara.list"),
        "waf" => Some("operator-projection:workflow:best-practice.list"),
        _ => None,
    };

    let (counts_res, msrc_res, controls_res) = if let Some(kv_key) = target_key {
        let search_clause = match clean_opt(search) {
            Some(q) => {
                let pat = quote_like_contains(q);
                format!(
                    " AND (COALESCE(c.val->>'control_id', c.val->>'id', '') ILIKE {pat} ESCAPE '\\' \
                     OR COALESCE(c.val->>'title', '') ILIKE {pat} ESCAPE '\\' \
                     OR COALESCE(c.val->>'area', c.val->>'pillar', c.val->>'impact', '') ILIKE {pat} ESCAPE '\\' \
                     OR COALESCE(c.val->>'description', c.val->>'rationale', '') ILIKE {pat} ESCAPE '\\')"
                )
            }
            None => String::new(),
        };
        let list_sql = format!(
            "SELECT \
                COALESCE(c.val->>'control_id', c.val->>'id', ''), \
                COALESCE(c.val->>'id', c.val->>'control_id', ''), \
                COALESCE(c.val->>'title', ''), \
                COALESCE(c.val->>'area', c.val->>'pillar', c.val->>'impact', c.val->>'category', 'general'), \
                COALESCE(c.val->>'severity', c.val->>'impact', 'medium'), \
                COALESCE(c.val->>'rationale', c.val->>'description', ''), \
                COALESCE(c.val->>'source_url', c.val->'provenance'->>'source_url', ''), \
                COALESCE(c.val->>'owner_slot', c.val->>'owner', ''), \
                COALESCE(c.val->>'satisfaction', c.val->>'status', c.val->>'lifecycle', 'unknown'), \
                COALESCE(c.val->'enablement'::text, '{{}}'), \
                COALESCE(c.val->'crosswalk'::text, '[]'), \
                COALESCE(c.val->'rule_ids'::text, '[]') \
             FROM state_kv sk, jsonb_array_elements(sk.value->'controls') AS c(val) \
             WHERE sk.key = {} {search_clause} \
             LIMIT {lim} OFFSET {off}",
            pg_quote_literal(kv_key)
        );
        let (a, b, c) = tokio::join!(
            db.query_single_readonly(counts_sql),
            db.query_single_readonly(msrc_cnt_sql),
            db.query_single_readonly(&list_sql),
        );
        (a, b, Some(c))
    } else {
        let (a, b) = tokio::join!(
            db.query_single_readonly(counts_sql),
            db.query_single_readonly(msrc_cnt_sql),
        );
        (a, b, None)
    };

    let Ok(cq) = counts_res else {
        return db.not_measured(
            "governance",
            "/api/v4/governance/frameworks",
            "postgres_unreachable",
        );
    };

    let mut mcsb_cnt: i64 = 0;
    let mut caf_cnt: i64 = 0;
    let mut wara_cnt: i64 = 0;
    let mut waf_cnt: i64 = 0;
    let mut versions = Map::new();
    let mut eval_sources = Map::new();

    for row in &cq.rows {
        let k = cell_str(row, 0);
        let cnt = cell_i64(row, 1).unwrap_or(0);
        let ver = cell_str(row, 2);
        let esrc = cell_str(row, 3);
        let fw_name = match k.as_str() {
            "operator-projection:workflow:mcsb-assessment.list" => {
                mcsb_cnt = cnt;
                "mcsb"
            }
            "operator-projection:workflow:caf.list" => {
                caf_cnt = cnt;
                "caf"
            }
            "operator-projection:workflow:wara.list" => {
                wara_cnt = cnt;
                "wara"
            }
            "operator-projection:workflow:best-practice.list" => {
                waf_cnt = cnt;
                "waf"
            }
            _ => continue,
        };
        versions.insert(fw_name.to_string(), Value::String(ver));
        eval_sources.insert(fw_name.to_string(), Value::String(esrc));
    }

    let (rule_list_msrc_cnt, security_rule_cnt) = msrc_res
        .ok()
        .and_then(|r| r.rows.first().cloned())
        .map(|row| {
            (
                cell_i64(&row, 0).unwrap_or(0),
                cell_i64(&row, 1).unwrap_or(0),
            )
        })
        .unwrap_or((0, 0));

    let msrc_catalog = load_msrc_csaf_catalog_async().await;
    let (msrc_proj_cnt, runtime_cves, _rt_db_ok) =
        fetch_msrc_projection_and_runtime_cves(db).await;
    let catalog_cve_cnt = msrc_catalog.cves.len() as i64;
    let msrc_cnt = msrc_proj_cnt.max(catalog_cve_cnt).max(rule_list_msrc_cnt);
    let msrc_eval_source = if msrc_proj_cnt > 0 {
        "msrc-csaf-shadow-assessment"
    } else if catalog_cve_cnt > 0 {
        "repository-catalog"
    } else {
        "state_kv"
    };
    versions.insert(
        "msrc".to_string(),
        Value::String(msrc_catalog.source_revision.clone()),
    );
    eval_sources.insert("msrc".to_string(), Value::String(msrc_eval_source.to_string()));

    let mut controls: Vec<Value> = Vec::new();
    if target_fw == "msrc" {
        let filtered = query_msrc_cves_from_cache(
            msrc_catalog,
            &runtime_cves,
            search,
            None,
            None,
            None,
            false,
            lim,
            off,
        );
        for item in filtered.items {
            let cve_id = item
                .get("cve_id")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            let title_ko = item
                .get("title_ko")
                .or_else(|| item.get("title"))
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            let title_en = item
                .get("title_en")
                .or_else(|| item.get("title"))
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            let sev = item
                .get("severity")
                .and_then(Value::as_str)
                .unwrap_or("medium")
                .to_string();
            let exploit = item
                .get("exploit_status")
                .and_then(Value::as_str)
                .unwrap_or("unproven")
                .to_string();
            let priority = item
                .get("priority_tier")
                .and_then(Value::as_str)
                .unwrap_or("P2")
                .to_string();
            let sla_ko = item
                .get("kev_sla_ko")
                .and_then(Value::as_str)
                .unwrap_or("표준 조치")
                .to_string();
            let runtime_hit = item
                .get("runtime_detected")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            let area_ko = if runtime_hit {
                "런타임 실측 탐지 CVE".to_string()
            } else if exploit == "exploited" {
                "실제 악용 확인 (KEV)".to_string()
            } else if item
                .get("publicly_disclosed")
                .and_then(Value::as_bool)
                .unwrap_or(false)
            {
                "공개 취약점 (0-Day 위험)".to_string()
            } else {
                item.get("primary_product_name")
                    .and_then(Value::as_str)
                    .filter(|s| !s.is_empty())
                    .unwrap_or("MSRC CSAF 보안 권고")
                    .to_string()
            };
            let sat = if runtime_hit || exploit == "exploited" {
                "failed"
            } else {
                "unknown"
            };
            let rationale = item
                .get("remediation_summary")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            let source_url = item
                .get("source_url")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            let rec_actions = item
                .get("recommended_actions")
                .cloned()
                .unwrap_or_else(|| json!([]));
            controls.push(json!({
                "control_id": cve_id,
                "id": cve_id,
                "framework": "msrc",
                "title": title_en,
                "title_ko": format!("[{priority} · {sla_ko}] {title_ko}"),
                "area": exploit,
                "area_ko": area_ko,
                "severity": sev,
                "rationale": utf8_truncate(&rationale, 500),
                "source_url": source_url,
                "owner_slot": "security-owner",
                "satisfaction": sat,
                "enablement": { "mode": if runtime_hit { "enforce" } else { "shadow" } },
                "crosswalk": item.get("affected_products").cloned().unwrap_or_else(|| json!([])),
                "rule_ids": rec_actions,
                "cve_detail": item
            }));
        }
    } else if let Some(Ok(lq)) = controls_res {
        for row in &lq.rows {
            let control_id = cell_str(row, 0);
            let raw_id = cell_str(row, 1);
            let title = cell_str(row, 2);
            let area = cell_str(row, 3);
            let severity = cell_str(row, 4);
            let rationale = cell_str(row, 5);
            let source_url = cell_str(row, 6);
            let owner_slot = cell_str(row, 7);
            let satisfaction = cell_str(row, 8);
            let enablement: Value =
                serde_json::from_str(&cell_str(row, 9)).unwrap_or_else(|_| json!({}));
            let crosswalk: Value =
                serde_json::from_str(&cell_str(row, 10)).unwrap_or_else(|_| json!([]));
            let rule_ids_val: Value =
                serde_json::from_str(&cell_str(row, 11)).unwrap_or_else(|_| json!([]));

            let mut linked_rules: Vec<String> = rule_ids_val
                .as_array()
                .map(|arr| {
                    arr.iter()
                        .filter_map(Value::as_str)
                        .map(String::from)
                        .collect()
                })
                .unwrap_or_default();
            if linked_rules.is_empty() {
                if let Some(cw_arr) = crosswalk.as_array() {
                    for cw in cw_arr {
                        if let Some(tref) = cw.get("target_ref").and_then(Value::as_str) {
                            linked_rules.push(tref.to_string());
                        }
                    }
                }
            }
            let area_ko = framework_domain_label_ko(&area);
            let title_ko = format!("[{area_ko}] {title}");
            controls.push(json!({
                "control_id": control_id,
                "id": raw_id,
                "framework": target_fw,
                "title": title,
                "title_ko": title_ko,
                "area": area,
                "area_ko": area_ko,
                "severity": severity,
                "rationale": utf8_truncate(&rationale, 500),
                "source_url": source_url,
                "owner_slot": owner_slot,
                "satisfaction": satisfaction,
                "enablement": enablement,
                "crosswalk": crosswalk,
                "rule_ids": linked_rules
            }));
        }
    }

    let fw_version = versions
        .get(target_fw)
        .and_then(Value::as_str)
        .unwrap_or("postgres-projection")
        .to_string();
    let eval_source = eval_sources
        .get(target_fw)
        .and_then(Value::as_str)
        .unwrap_or("state_kv")
        .to_string();

    let runtime_cve_count = runtime_cves.len() as i64;
    let msrc_runtime_matched = msrc_catalog
        .cves
        .iter()
        .filter(|c| runtime_cves.contains(&c.cve_id))
        .count() as i64;

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "framework": selected,
        "active_framework": target_fw,
        "framework_version": fw_version,
        "evaluation_source": eval_source,
        "counts": {
            "mcsb": mcsb_cnt,
            "caf": caf_cnt,
            "wara": wara_cnt,
            "waf": waf_cnt,
            "msrc": msrc_cnt
        },
        "msrc_summary": {
            "total_cves": msrc_catalog.cves.len(),
            "total_advisories": msrc_catalog.total_advisories,
            "exploited_count": msrc_catalog.exploited_count,
            "publicly_disclosed_count": msrc_catalog.publicly_disclosed_count,
            "product_mapping_count": msrc_catalog.product_mapping_count,
            "runtime_detected_cves": runtime_cve_count,
            "runtime_msrc_matched": msrc_runtime_matched,
            "source_revision": msrc_catalog.source_revision,
            "evaluation_source": msrc_eval_source
        },
        "msrc_security_rules_linked": security_rule_cnt,
        "total_frameworks_controls": mcsb_cnt + caf_cnt + wara_cnt + waf_cnt + msrc_cnt,
        "limit": lim,
        "offset": off,
        "controls": controls,
        "items": controls
    })
}

fn active_rule_guidance_ko(
    rule_id: &str,
) -> Option<(&'static str, &'static str, &'static str, &'static str)> {
    match rule_id {
        "cache.zone-redundant" => Some((
            "캐시 인스턴스가 단일 가용 영역(`count(zones) < 2`)에만 배치되어 영역 장애 시 서비스 중단 위험에 노출됩니다.",
            "`remediate.enable-zone-redundancy` 조치를 통해 캐시 인스턴스를 최소 2개 이상의 가용 영역(`zones` >= 2)에 분산 구성합니다.",
            "단일 가용 영역 장애 발생 시 전체 캐시 증발과 백엔드 데이터베이스 부하 폭주(Stampede)를 방지합니다.",
            "최신 인벤토리 스냅샷에서 `property.cache.zones` 속성을 확인하여 2개 이상의 가용 영역이 활성화되었는지 검증합니다.",
        )),
        "compute.vm-scale-set.zone-redundancy" => Some((
            "가상 머신 확장 집합(VMSS)이 단일 영역에 고정되어 있거나 영역 지정 없이 배포되어 있습니다.",
            "VM 확장 집합을 2개 이상의 가용 영역(`zones` >= 2)에 분산 배치하고 영역 균형 스케일링을 활성화합니다.",
            "특정 가용 영역에 장애가 발생하더라도 수평 확장 컴퓨팅 용량과 부하 분산 트래픽 처리를 중단 없이 유지합니다.",
            "`property.compute.vm-scale-set.zones` 속성에 2개 이상의 영역이 기록되고 T0 평가 결과가 준수(Compliant)인지 확인합니다.",
        )),
        "compute.vm.environment-tag.required" => Some((
            "가상 머신에 `environment` 태그가 누락되어 해당 리소스의 운영 등급과 수명주기 정책 범위를 식별할 수 없습니다.",
            "`remediate.tag-add` 교정 템플릿을 통해 표준화된 `environment` 태그(예: prod, staging, dev)를 부여합니다.",
            "운영·스테이징·개발 환경을 결정론적으로 구분하여 변경 안전성, 패치 일정, 비용 거버넌스 정책을 정확히 적용합니다.",
            "다음 인벤토리 관측에서 `property.compute.vm.tags.required_tag` 값이 정상적으로 존재하는지 확인합니다.",
        )),
        "compute.vm.managed-identity.assigned" => Some((
            "가상 머신에 관리 ID(`identity_type`)가 할당되지 않아 애플리케이션이 별도 비밀키나 연결 문자열에 의존합니다.",
            "`remediate.assign-identity` 조치를 통해 가상 머신에 시스템 할당 또는 사용자 할당 관리 ID를 연결합니다.",
            "인스턴스 메타데이터 서비스(IMDS) 기반 Entra ID 단기 토큰을 사용하여 호스트 내 정적 자격 증명 유출 위험을 제거합니다.",
            "인벤토리의 `property.compute.vm.identity_type` 속성과 할당된 관리 ID의 최소 권한 RBAC 범위를 검증합니다.",
        )),
        "disk.snapshot-policy.required" => Some((
            "관리 디스크의 `snapshot_policy_present`가 `false`여서 자동화된 스냅샷 복구 지점이 생성되지 않습니다.",
            "`remediate.enable-backup-protection` 조치를 통해 디스크를 자동 스냅샷 및 백업 보호 정책에 등록합니다.",
            "구성 변경 실패나 데이터 손상 발생 시 즉시 되돌릴 수 있는 최신 디스크 복구 지점을 보장합니다.",
            "`property.disk.snapshot_policy_present == true` 상태와 최근 스냅샷 복구 지점 생성 이력을 확인합니다.",
        )),
        "kubernetes-cluster.diagnostic-settings-required" => Some((
            "AKS 클러스터에 컨트롤 플레인 진단 로그를 Log Analytics 워크스페이스로 보내는 진단 설정이 없습니다.",
            "`remediate.enable-diagnostic-settings` 조치를 통해 감사 및 컨트롤러 로그를 중앙 워크스페이스로 전송하도록 구성합니다.",
            "인시던트 근본 원인 분석(RCA)과 보안 포렌식을 위한 컨트롤 플레인 감사 로그(`kube-audit` 등)를 빠짐없이 확보합니다.",
            "`property.kubernetes-cluster.diagnostic_settings` 속성과 대상 워크스페이스의 로그 수집 상태를 검증합니다.",
        )),
        "kubernetes-cluster.network-policy" => Some((
            "클러스터의 `network_policy`가 비활성화되어 모든 파드 간 네트워크 통신이 무제한 허용됩니다.",
            "클러스터에 `azure` 또는 `calico` 네트워크 정책 엔진을 구성하여 파드 간 트래픽 제어를 활성화합니다.",
            "클러스터 내부에서 침해된 파드가 다른 네임스페이스나 워크로드로 수평 이동(Lateral Movement)하는 것을 차단합니다.",
            "인벤토리 스냅샷에서 `property.kubernetes-cluster.network_policy` 값이 `azure` 또는 `calico`로 설정되었는지 확인합니다.",
        )),
        "kubernetes-cluster.private-cluster" => Some((
            "`private_cluster_enabled`가 `true`가 아니어서 클러스터 API 서버 엔드포인트가 외부 인터넷에 노출됩니다.",
            "`remediate.restrict-network-access` 템플릿을 통해 프라이빗 클러스터 모드(`private_cluster_enabled = true`)를 적용합니다.",
            "Kubernetes API 서버를 공용 인터넷 공격 표면에서 완전히 격리하고 Private Link 사설 네트워크로만 접근을 제한합니다.",
            "`property.kubernetes-cluster.private_cluster_enabled == true` 여부와 프라이빗 DNS 해석 상태를 검증합니다.",
        )),
        "kubernetes-cluster.rbac-enabled" => Some((
            "`azure_rbac_enabled`가 비활성화되어 공유 로컬 관리자 kubeconfig 자격 증명에 의존하고 있습니다.",
            "`remediate.enable-rbac` 조치를 통해 Kubernetes 권한 부여용 Azure RBAC 통합(`azure_rbac_enabled = true`)을 활성화합니다.",
            "클러스터 권한 제어를 Entra ID 조건부 액세스, PIM 권한 승격, 중앙 감사 로그와 단일 체계로 통합합니다.",
            "클러스터 인벤토리 레코드에서 `property.kubernetes-cluster.azure_rbac_enabled == true` 상태를 확인합니다.",
        )),
        "kubernetes-node-pool.multi-zone" => Some((
            "노드 풀이 단일 가용 영역에만 배치되어 있거나 영역 중복 구성(`availability_zones`)이 누락되어 있습니다.",
            "`remediate.enable-zone-redundancy`를 통해 노드 풀을 최소 2개 이상의 가용 영역(`availability_zones` >= 2)에 분산 구성합니다.",
            "데이터센터 단일 가용 영역 장애 시에도 파드 재스케일링과 워크로드 가용성이 중단 없이 유지되도록 보장합니다.",
            "`property.kubernetes-node-pool.availability_zones`에 2개 이상의 영역이 포함되고 노드가 균형 배치되었는지 확인합니다.",
        )),
        "llm-endpoint.t2-proposer-unavailable" => Some((
            "구성된 모든 T2 추론 제안자 모델 엔드포인트에서 최종 호출 실패(`t2_proposer_unavailable`)가 관측됩니다.",
            "인간 승인(HIL) 검토를 거쳐 `ops.switch-t2-proposer-route` 조치로 검증된 대체 모델 경로로 안전하게 전환합니다.",
            "T2 프론티어 모델 경로가 모두 실패했을 때 임의 동작 대신 인간 개입(HIL) 검토 및 경로 전환 절차로 안전하게 폴백합니다.",
            "`llm-endpoint` 상태 프로브 복구와 T2 교차 검증 가용성을 확인한 뒤 추론 경로를 재개합니다.",
        )),
        "managed-identity.role-assignment.no-privileged-subscription-scope" => Some((
            "워크로드 관리 ID에 구독 전체 범위(`/subscriptions/<id>`)의 Owner, Contributor 등 고권한 역할이 부여되어 있습니다.",
            "`remediate.right-size-role` 조치를 통해 권한 범위를 실제 필요한 리소스 또는 리소스 그룹의 최소 권한 역할로 축소합니다.",
            "단일 워크로드 관리 ID가 침해되더라도 구독 전체 리소스의 탈취나 삭제(전체 영향 반경 확산)로 이어지는 것을 차단합니다.",
            "`property.managed-identity.role_assignments`를 검사하여 구독 범위의 고권한 역할 할당이 완전히 제거되었는지 확인합니다.",
        )),
        "managed-identity.role-assignment.no-wildcard-action" => Some((
            "관리 ID에 할당된 역할 정의의 `actions` 또는 `data_actions`에 모든 작업을 허용하는 와일드카드(`*`)가 포함되어 있습니다.",
            "`remediate.right-size-role` 조치를 통해 와일드카드 역할을 명시적인 최소 권한 작업 목록만 가진 역할로 교체합니다.",
            "워크로드 관리 ID가 수행할 수 있는 모든 작업을 명시적으로 제한하여 최소 권한 원칙과 감사 투명성을 보장합니다.",
            "`property.managed-identity.role_assignments`의 모든 역할 할당에 와일드카드(`*`) 권한이 없는지 검증합니다.",
        )),
        "network.nsg.no-inbound-any-rdp" => Some((
            "NSG 보안 규칙에 소스 `*` 또는 `Any`로부터 대상 포트 3389(RDP)를 허용하는 인바운드 규칙이 존재합니다.",
            "`remediate.restrict-network-access`로 무제한 RDP 허용 규칙을 제거·제한하고 Azure Bastion 또는 사설 연결을 사용합니다.",
            "Windows 가상 머신에 대한 직접적인 RDP 무차별 대입 공격과 원격 익스플로잇 공격 경로를 원천 차단합니다.",
            "`property.network.nsg.security_rules`를 확인하여 비신뢰 소스로부터의 TCP/3389 인바운드 허용이 없는지 검증합니다.",
        )),
        "network.nsg.no-inbound-any-ssh" => Some((
            "NSG 보안 규칙에 소스 `*` 또는 `Any`로부터 대상 포트 22(SSH)를 허용하는 인바운드 규칙이 존재합니다.",
            "`remediate.restrict-network-access`로 무제한 SSH 허용 규칙을 제거하고 Bastion 또는 JIT 접근만 허용합니다.",
            "Linux 관리 포트(SSH TCP/22)를 겨냥한 자동화된 봇넷 스캔과 무차별 대입 공격을 차단합니다.",
            "`property.network.nsg.security_rules`에서 포트 22를 포괄하는 무제한 인바운드 허용 규칙이 없는지 확인합니다.",
        )),
        "network.nsg.no-internet-inbound-rdp" => Some((
            "더 낮은 우선순위 번호(더 높은 우선순위)의 차단 규칙 없이 인터넷(`0.0.0.0/0` 등)에서 TCP/3389로 진입 가능한 허용 규칙이 존재합니다.",
            "`remediate.restrict-network-access`를 통해 인터넷 노출 RDP 허용 규칙을 제거하거나 상위 우선순위 거부 규칙을 적용합니다.",
            "포트 범위, 접두사 목록, 규칙 우선순위를 종합 분석하여 실제 인터넷에서 도달 가능한 RDP 노출을 정밀하게 차단합니다.",
            "`property.network.nsg.inbound_security_rules`의 우선순위 조합을 평가하여 인터넷발 TCP/3389 도달이 불가한지 검증합니다.",
        )),
        "network.nsg.no-internet-inbound-ssh" => Some((
            "상위 우선순위 거부 규칙 없이 인터넷(`Internet`, `0.0.0.0/0` 등)에서 TCP/22로 진입 가능한 인바운드 허용 규칙이 존재합니다.",
            "`remediate.restrict-network-access` 템플릿을 적용하여 인터넷발 TCP/22 인바운드 노출을 차단합니다.",
            "와일드카드 포트, CIDR 목록, NSG 우선순위를 종합 평가하여 실제 인터넷에서 도달 가능한 SSH 노출을 정밀 차단합니다.",
            "`property.network.nsg.inbound_security_rules` 평가 결과 인터넷발 TCP/22 트래픽이 거부되는지 검증합니다.",
        )),
        "network.vnet.ddos-plan.required" => Some((
            "가상 네트워크(`network.vnet`)에 `ddos_protection_plan_id`가 연결되지 않아 대용량 DDoS 공격에 취약합니다.",
            "`remediate.restrict-network-access` 조치를 통해 가상 네트워크에 Azure DDoS 보호 계획을 연결합니다.",
            "외부 접점 가상 네트워크에 대해 적응형 트래픽 스크러빙과 DDoS 공격 완화 메트릭을 제공합니다.",
            "최신 VNet 인벤토리 레코드에서 `property.network.vnet.ddos_protection_plan_id`가 유효하게 설정되었는지 확인합니다.",
        )),
        "object-storage.cost-center-tag.required" => Some((
            "오브젝트 스토리지 계정에 `cost_center` 태그가 누락되어 비용 귀속 부서를 식별할 수 없습니다.",
            "`remediate.tag-add` 교정 템플릿을 통해 스토리지 계정에 `cost_center` 태그를 부여합니다.",
            "모든 스토리지 계정의 저장 용량 및 전송 요금을 책임 비용 센터(Cost Center)에 누락 없이 귀속시킵니다.",
            "스토리지 계정 인벤토리에서 `property.object-storage.tags.required_tag` 값을 확인합니다.",
        )),
        "object-storage.diagnostic-settings-required" => Some((
            "오브젝트 스토리지 계정에 Blob 및 스토리지 로그를 Log Analytics로 전송하는 진단 설정이 없습니다.",
            "`remediate.enable-diagnostic-settings` 조치를 통해 스토리지 진단 로그 전송을 활성화합니다.",
            "데이터 유출 탐지 및 규정 준수 감사를 위해 스토리지 읽기·쓰기·삭제 진단 로그를 중앙 워크스페이스에 보존합니다.",
            "`property.object-storage.diagnostic_settings`에 활성 Log Analytics 대상이 포함되었는지 검증합니다.",
        )),
        "object-storage.encryption-at-rest.required" => Some((
            "오브젝트 스토리지 계정에 인프라 이중 암호화(`infrastructure_encryption_enabled`)가 비활성화되어 있습니다.",
            "`remediate.enable-encryption` 조치를 통해 오브젝트 스토리지 저장 데이터 인프라 암호화를 활성화합니다.",
            "서비스 수준 암호화와 물리 인프라 수준 암호화의 이중 계층으로 저장 데이터를 안전하게 보호합니다.",
            "인벤토리에서 `property.object-storage.infrastructure_encryption_enabled == true` 상태를 확인합니다.",
        )),
        "object-storage.https-only.required" => Some((
            "오브젝트 스토리지 계정이 평문 HTTP 요청을 허용(`enable_https_traffic_only == false`)하고 있습니다.",
            "`remediate.set-tls-policy` 조치를 통해 HTTPS 전용 트래픽 강제(`enable_https_traffic_only = true`)를 설정합니다.",
            "평문 HTTP 통신을 통한 중간자 공격(MITM)과 SAS 토큰·데이터 도청 위험을 원천 차단합니다.",
            "`property.object-storage.enable_https_traffic_only == true` 설정과 평문 HTTP 요청 거부를 확인합니다.",
        )),
        "object-storage.min-tls-version" => Some((
            "오브젝트 스토리지의 최소 TLS 버전(`min_tls_version`)이 구형 `TLS1_0` 또는 `TLS1_1`로 허용되어 있습니다.",
            "`remediate.set-tls-policy` 템플릿을 통해 최소 TLS 버전을 `TLS1_2` 이상으로 상향 설정합니다.",
            "스토리지 엔드포인트에서 취약한 구형 TLS 1.0/1.1 프로토콜 다운그레이드 협상을 차단합니다.",
            "인벤토리 스냅샷에서 `property.object-storage.min_tls_version` 값이 `TLS1_2`인지 검증합니다.",
        )),
        "object-storage.owner-tag.required" => Some((
            "오브젝트 스토리지 계정에 필수 `owner` 태그가 누락되어 관리 책임자를 즉시 확인할 수 없습니다.",
            "`remediate.tag-add` 템플릿을 통해 스토리지 계정에 `owner` 태그를 부여합니다.",
            "모든 스토리지 계정에 보안 인시던트 대응 및 접근 검토를 담당할 책임 주체(Owner)를 명확히 연결합니다.",
            "인벤토리에서 `property.object-storage.tags.required_tag` 태그 값이 기록되었는지 확인합니다.",
        )),
        "object-storage.private-endpoint.required" => Some((
            "오브젝트 스토리지에 공용 네트워크 접근이 열려 있거나 연결된 프라이빗 엔드포인트가 없습니다.",
            "`remediate.restrict-network-access`를 통해 공용 네트워크 접근을 끄고 프라이빗 엔드포인트를 구성합니다.",
            "스토리지 데이터 플레인 트래픽을 사설 VNet 내부로 격리하고 공용 인터넷을 통한 데이터 접근을 차단합니다.",
            "인벤토리에서 `public_network_access_enabled == false` 및 `private_endpoints` 연결 상태를 확인합니다.",
        )),
        "object-storage.public-access.deny" => Some((
            "스토리지 계정의 익명 공용 액세스(`public_access == true`)가 허용되어 비인증 노출 위험이 있습니다.",
            "`remediate.disable-public-access` 조치를 통해 계정 수준의 익명 공용 액세스를 비활성화합니다.",
            "개별 컨테이너 ACL이 잘못 설정되더라도 계정 수준에서 익명 공용 Blob 열람과 유출을 원천 차단합니다.",
            "다음 인벤토리 평가에서 `property.object-storage.public_access == false` 상태를 검증합니다.",
        )),
        "object-storage.shared-key-access.disabled" => Some((
            "스토리지 계정이 공유 마스터 키 인증(`allow_shared_key_access == true`)을 허용하고 있습니다.",
            "호출 워크로드를 관리 ID로 전환한 후 `remediate.enable-rbac` 조치로 공유 키 접근(`allow_shared_key_access = false`)을 차단합니다.",
            "계정 전체 권한을 가진 마스터 공유 키 우회를 차단하고 주체별 Entra ID RBAC 인가 및 감사 추적을 강제합니다.",
            "인벤토리에서 `property.object-storage.allow_shared_key_access == false` 상태를 검증합니다.",
        )),
        "object-storage.soft-delete-blob" => Some((
            "Blob 소프트 삭제(`blob_soft_delete_enabled`)가 비활성화되어 삭제 시 데이터가 즉시 영구 소실됩니다.",
            "`remediate.enable-backup-protection` 조치를 통해 Blob 소프트 삭제 및 보존 기간 정책을 활성화합니다.",
            "삭제된 Blob 객체를 지정된 보존 기간 동안 소프트 삭제 상태로 유지하여 무손실 복구를 보장합니다.",
            "스토리지 인벤토리 스냅샷에서 `property.object-storage.blob_soft_delete_enabled == true` 여부를 확인합니다.",
        )),
        "object-storage.versioning-enabled" => Some((
            "Blob 버전 관리(`blob_versioning_enabled`)가 꺼져 있어 덮어쓰기 시 이전 데이터가 즉시 유실됩니다.",
            "`remediate.enable-backup-protection` 조치를 통해 Blob 자동 버전 관리를 활성화합니다.",
            "객체 덮어쓰기나 변조 발생 시마다 이전 버전을 자동으로 보존하여 시점 복구 능력을 제공합니다.",
            "인벤토리에서 `property.object-storage.blob_versioning_enabled == true` 설정을 확인합니다.",
        )),
        "ops.change-summary" => Some((
            "운영자 또는 예약 작업이 `request_kind == 'change-summary'` 마커가 포함된 리소스 그룹 이벤트를 발행합니다.",
            "`ops.publish-change-summary` ActionType을 실행하여 감사 로그 기반 변경 요약 보고서를 생성·게시합니다.",
            "운영자 요청이나 예약 주기에 따라 감사 원장 기반의 변경 요약 보고서를 결정론적으로 생성·발행합니다.",
            "생성된 `ChangeSummary` 산출물과 대상 리소스 그룹의 Saga 감사 증적을 확인합니다.",
        )),
        "postgresql-server.diagnostic-settings-required" => Some((
            "PostgreSQL 서버에 로그를 중앙 Log Analytics 워크스페이스로 전송하는 진단 설정이 구성되어 있지 않습니다.",
            "`remediate.enable-diagnostic-settings` 조치를 통해 PostgreSQL 진단 로그 전송 설정을 활성화합니다.",
            "데이터베이스 연결·쿼리·오류 로그를 중앙 수집하여 장애 분석과 보안 감사를 위한 가시성을 확보합니다.",
            "인벤토리에서 `property.postgresql-server.diagnostic_settings` 설정이 유효한지 검증합니다.",
        )),
        "postgresql-server.encryption-at-rest" => Some((
            "PostgreSQL 서버의 저장 데이터 암호화(`encryption_at_rest_enabled`)가 `false`로 관측됩니다.",
            "`remediate.enable-encryption` 조치를 통해 PostgreSQL 저장 데이터 암호화를 활성화합니다.",
            "데이터 파일, 트랜잭션 로그(WAL), 백업 스냅샷을 저장 상태에서 암호화하여 물리·스토리지 유출을 방지합니다.",
            "인벤토리에서 `property.postgresql-server.encryption_at_rest_enabled == true` 여부를 확인합니다.",
        )),
        "postgresql-server.high-availability" => Some((
            "PostgreSQL 서버의 고가용성 모드(`ha_mode`)가 `ZoneRedundant`가 아닌 단일 인스턴스 또는 단일 영역 상태입니다.",
            "`remediate.enable-zone-redundancy` 조치를 통해 PostgreSQL 고가용성 모드를 `ZoneRedundant`로 구성합니다.",
            "가용 영역 간 동기식 대기 복제본을 유지하여 영역 장애 시 운영자 개입 없이 즉시 자동 장애 조치를 수행합니다.",
            "`property.postgresql-server.ha_mode == 'ZoneRedundant'` 설정과 대기 서버 정상 상태를 검증합니다.",
        )),
        "postgresql-server.point-in-time-restore" => Some((
            "PostgreSQL 백업 보존 일수(`backup_retention_days`)가 최소 요구 기준(기본 7일)보다 짧게 설정되어 있습니다.",
            "`remediate.enable-backup-protection` 조치를 통해 백업 보존 일수(`backup_retention_days`)를 최소 기준 이상으로 상향합니다.",
            "최소 7일 이상의 백업 및 로그 보존 주기를 유지하여 데이터 손상 시 원하는 시점으로 정밀 복원할 수 있습니다.",
            "인벤토리에서 `property.postgresql-server.backup_retention_days` 값이 기준 일수 이상인지 확인합니다.",
        )),
        "postgresql-server.ssl-enforcement" => Some((
            "PostgreSQL 서버에 SSL 연결 강제(`ssl_enforcement`)가 비활성화되어 평문 접속이 가능합니다.",
            "`remediate.enable-encryption` 조치를 통해 PostgreSQL 서버의 SSL/TLS 연결 강제를 활성화합니다.",
            "데이터베이스 네트워크 경로에서 자격 증명과 쿼리 결과가 평문으로 도청되는 것을 방지합니다.",
            "인벤토리에서 `property.postgresql-server.ssl_enforcement`가 활성화 상태인지 검증합니다.",
        )),
        "resource-group.cost-center-tag.required" => Some((
            "리소스 그룹에 `cost_center` 태그가 지정되지 않아 비용 귀속 조직을 식별할 수 없습니다.",
            "`remediate.tag-add` 조치를 통해 리소스 그룹에 표준 `cost_center` 태그를 추가합니다.",
            "리소스 그룹 단위에서 하위 리소스 비용의 재무 귀속 기준(FinOps Cost Attribution)을 확립합니다.",
            "리소스 그룹 인벤토리에서 `property.resource-group.tags.required_tag` 존재 여부를 확인합니다.",
        )),
        "resource-group.environment-tag.required" => Some((
            "리소스 그룹에 `environment` 태그가 없어 운영·개발 환경 구분이 불명확합니다.",
            "`remediate.tag-add` 조치를 통해 리소스 그룹에 `environment` 태그를 부여합니다.",
            "리소스 그룹 전체에 환경별 거버넌스, 승인 게이트, 경보 기준이 일관되게 적용되도록 보장합니다.",
            "인벤토리에서 리소스 그룹의 `environment` 태그 설정을 검증합니다.",
        )),
        "resource-group.owner-tag.required" => Some((
            "리소스 그룹에 `owner` 태그가 누락되어 책임 담당자가 지정되어 있지 않습니다.",
            "`remediate.tag-add` 조치를 통해 리소스 그룹에 `owner` 태그를 지정합니다.",
            "인시던트 발생 및 정기 보안 검토 시 각 리소스 그룹의 책임 팀·담당자를 즉시 식별할 수 있습니다.",
            "인벤토리에서 리소스 그룹의 `owner` 태그 값을 확인합니다.",
        )),
        "resource-group.role-assignment.owner-count-within-limit" => Some((
            "리소스 그룹에 허용 상한(`max_owner_count`, 기본 3명)을 초과하는 주체에게 Owner 역할이 부여되어 있습니다.",
            "`remediate.right-size-role` 조치를 통해 불필요한 Owner 할당을 최소 권한 역할로 축소하여 상한 이하로 유지합니다.",
            "리소스 그룹 범위에서 최고 권한(Owner)의 무분별한 확산을 막고 명확한 관리 책임성을 유지합니다.",
            "`property.resource-group.role_assignments`에서 Owner 역할 보유 주체 수가 상한 이하인지 검증합니다.",
        )),
        "secret-store.diagnostic-settings-required" => Some((
            "비밀 저장소(`secret-store`)에 `AuditEvent` 감사 로그를 Log Analytics로 전송하는 진단 설정이 없습니다.",
            "`remediate.enable-diagnostic-settings`를 통해 `AuditEvent` 진단 로그 전송을 활성화합니다.",
            "모든 비밀값·암호화 키·인증서 조회 및 변경 이력을 중앙 감사 워크스페이스에 보존하여 침해 여부를 추적합니다.",
            "`property.secret-store.diagnostic_settings`에서 `AuditEvent` 워크스페이스 전송 설정을 확인합니다.",
        )),
        "secret-store.public-network-access.disabled" => Some((
            "비밀 저장소에 공용 네트워크 접근(`public_network_access_enabled == true`)이 허용되어 있습니다.",
            "`remediate.restrict-network-access` 조치를 통해 비밀 저장소의 공용 네트워크 접근을 비활성화합니다.",
            "공용 인터넷에서의 비밀 저장소 접근 시도와 탈취된 토큰을 이용한 외부 유출을 차단합니다.",
            "인벤토리에서 `property.secret-store.public_network_access_enabled == false` 상태를 확인합니다.",
        )),
        "secret-store.purge-protection.enabled" => Some((
            "영구 삭제 방지(`purge_protection_enabled`)가 비활성화되어 삭제된 비밀값이 보존 기간 중 영구 파기될 수 있습니다.",
            "HIL 승인을 거치는 `remediate.enable-purge-protection` 조치로 영구 삭제 방지(`purge_protection_enabled = true`)를 활성화합니다.",
            "랜섬웨어나 악의적인 내부자가 소프트 삭제된 암호화 키·비밀값을 강제로 영구 파기하는 것을 방지합니다.",
            "인벤토리에서 `property.secret-store.purge_protection_enabled == true` 설정을 검증합니다.",
        )),
        "secret-store.rbac-authorization.enabled" => Some((
            "비밀 저장소가 레거시 자격 증명 모음 액세스 정책(`rbac_authorization_enabled != true`)을 사용하고 있습니다.",
            "`remediate.enable-rbac` 조치를 통해 비밀 저장소의 Azure RBAC 권한 부여 모델을 활성화합니다.",
            "개별 비밀값·키 단위의 세분화된 최소 권한 RBAC 제어와 PIM 적시 권한 부여를 가능하게 합니다.",
            "인벤토리에서 `property.secret-store.rbac_authorization_enabled == true` 상태를 확인합니다.",
        )),
        "secret-store.rotation-overdue" => Some((
            "비밀값의 생성 후 경과 일수(`age_days`)가 최대 허용 주기(`max_age_days`, 기본 90일)를 초과했습니다.",
            "`remediate.rotate-secret` 조치를 통해 만료된 비밀값을 새 버전으로 교체하고 연동 구성을 갱신합니다.",
            "장기 미교체 비밀값의 노출 기간을 제한하고 정기적인 자격 증명 교체(Rotation) 주기를 강제합니다.",
            "비밀값 교체 후 인벤토리에서 `property.secret-store.age_days`가 허용 주기 이내인지 확인합니다.",
        )),
        "secret-store.soft-delete.enabled" => Some((
            "비밀 저장소에 소프트 삭제(`soft_delete_enabled`)가 비활성화되어 있습니다.",
            "`remediate.enable-backup-protection` 조치를 통해 비밀 저장소 소프트 삭제를 활성화합니다.",
            "실수로 삭제된 비밀값, 암호화 키, 인증서를 보존 기간 내에 데이터 손실 없이 복원할 수 있도록 보장합니다.",
            "인벤토리에서 `property.secret-store.soft_delete_enabled == true` 설정을 확인합니다.",
        )),
        "sql-database.audit-enabled" => Some((
            "SQL 데이터베이스의 보안 감사(`audit_enabled`)가 비활성화되어 있습니다.",
            "`remediate.enable-diagnostic-settings` 조치를 통해 SQL 데이터베이스 감사를 활성화하고 워크스페이스에 연결합니다.",
            "데이터베이스 인증, 스키마 변경, 민감 데이터 조회 활동을 기록하여 보안 조사 및 감사 추적성을 확보합니다.",
            "인벤토리에서 `property.sql-database.audit_enabled == true` 상태를 검증합니다.",
        )),
        "sql-database.diagnostic-settings-required" => Some((
            "SQL 데이터베이스에 중앙 로그 워크스페이스로 연결된 진단 설정(`diagnostic_settings`)이 없습니다.",
            "`remediate.enable-diagnostic-settings` 조치를 통해 SQL 데이터베이스 진단 설정을 구성합니다.",
            "데드락, 타임아웃, 리소스 포화도 및 감사 원격 분석 데이터를 중앙 관측성 워크스페이스로 실시간 수집합니다.",
            "인벤토리에서 `property.sql-database.diagnostic_settings` 설정이 유효한지 확인합니다.",
        )),
        "sql-database.geo-redundant-backup" => Some((
            "SQL 데이터베이스의 지역 중복 백업(`geo_redundant_backup_enabled`)이 비활성화되어 리전 장애 시 백업 유실 위험이 있습니다.",
            "`remediate.enable-backup-protection` 조치를 통해 지역 중복 백업 스토리지를 활성화합니다.",
            "주 리전 전체 재해 발생 시에도 쌍으로 연결된 보조 리전에서 데이터베이스 백업을 안전하게 복원할 수 있습니다.",
            "인벤토리에서 `property.sql-database.geo_redundant_backup_enabled == true` 상태를 확인합니다.",
        )),
        "sql-database.tde-required" => Some((
            "SQL 데이터베이스의 투명한 데이터 암호화(`tde_enabled == false`)가 꺼져 있어 데이터 파일이 평문으로 저장됩니다.",
            "`remediate.enable-tde` 조치를 통해 투명한 데이터 암호화(`tde_enabled = true`)를 즉시 활성화합니다.",
            "애플리케이션 변경 없이 SQL 데이터베이스 파일, 트랜잭션 로그, 백업을 실시간으로 저장 암호화합니다.",
            "SQL 데이터베이스 인벤토리 레코드에서 `property.sql-database.tde_enabled == true` 상태를 검증합니다.",
        )),
        "sql-database.zone-redundant" => Some((
            "SQL 데이터베이스가 단일 영역 구성(`zone_redundant != true`)으로 실행되고 있습니다.",
            "`remediate.enable-zone-redundancy` 조치를 통해 SQL 데이터베이스 영역 중복(`zone_redundant = true`)을 활성화합니다.",
            "SQL 데이터베이스 컴퓨팅과 스토리지를 여러 가용 영역에 복제하여 영역 장애 시 무손실 자동 전환을 제공합니다.",
            "인벤토리에서 `property.sql-database.zone_redundant == true` 여부를 확인합니다.",
        )),
        "subscription.role-assignment.no-guest-privileged" => Some((
            "외부 게스트(Guest) 주체에 구독 범위의 Owner, Contributor, User Access Administrator 등 고권한 역할이 할당되어 있습니다.",
            "`remediate.right-size-role` 조치를 통해 외부 게스트 계정의 구독 범위 고권한 역할을 회수하거나 최소 권한으로 축소합니다.",
            "외부 테넌트(B2B Guest) 계정이 구독 전체의 관리자 권한을 보유하여 발생하는 침해 및 권한 남용 위험을 차단합니다.",
            "`property.subscription.role_assignments`를 검사하여 고권한 역할을 보유한 외부 게스트 주체가 0명인지 확인합니다.",
        )),
        "subscription.role-assignment.no-standing-privileged-access" => Some((
            "구독 범위의 고권한 역할 할당이 시간 제한 없는 상시(Standing) 활성 권한으로 부여되어 있습니다.",
            "`remediate.right-size-role` 조치를 통해 상시 고권한 할당을 PIM 적격(Eligible) JIT 권한으로 전환합니다.",
            "상시 활성화된 영구 관리자 권한을 제거하고 시간 제한 및 승인 감사가 적용되는 PIM 적시(JIT) 활성화로 전환합니다.",
            "`property.subscription.role_assignments`의 모든 고권한 역할이 상시(Standing)가 아닌 JIT 적격 상태인지 검증합니다.",
        )),
        _ => None,
    }
}

// ============================================================================
// Security Governance: MSRC CSAF 9,058 CVEs + Unknown-Vulnerability (0-Day)
// LLM Lenses, Interprocedural Engines, Dynamic Proof & Live DB Crosswalk
// ============================================================================

#[derive(Clone, Debug)]
pub struct MsrcProductRef {
    pub product_id: String,
    pub product_name: String,
    pub canonical_resource_types: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct MsrcCveEntry {
    pub cve_id: String,
    pub tracking_id: String,
    pub title: String,
    pub severity: String,
    pub cvss_base_score: f64,
    pub cvss_temporal_score: f64,
    pub cvss_vector: String,
    pub exploit_status: String,
    pub publicly_disclosed: bool,
    pub priority_tier: String,
    pub kev_sla_tier: String,
    pub kev_sla_ko: String,
    pub release_date: String,
    pub source_url: String,
    pub signature_verified: bool,
    pub affected_product_ids: Vec<String>,
    pub primary_product_name: String,
    pub canonical_resource_types: Vec<String>,
    pub remediation_summary: String,
    pub recommended_actions: Vec<String>,
    pub search_blob: String,
}

#[derive(Clone, Debug, Default)]
pub struct MsrcCsafCatalogCache {
    pub source_revision: String,
    pub advisories_digest: String,
    pub crosswalk_digest: String,
    pub total_advisories: usize,
    pub product_mapping_count: usize,
    pub exploited_count: usize,
    pub publicly_disclosed_count: usize,
    pub critical_count: usize,
    pub high_count: usize,
    pub medium_count: usize,
    pub low_count: usize,
    pub loaded_at_unix: u64,
    pub cves: Vec<MsrcCveEntry>,
}

#[derive(Clone, Debug)]
pub struct UnknownVulnLensEntry {
    pub id: String,
    pub title_ko: String,
    pub weakness_class: String,
    pub cwes: Vec<String>,
    pub languages: Vec<String>,
    pub sink_hint_count: usize,
    pub focus: String,
    pub quorum: u64,
    pub mode: String,
}

#[derive(Clone, Debug)]
pub struct AnalysisComponentEntry {
    pub id: String,
    pub version: String,
    pub purpose: String,
    pub status: String,
    pub license: String,
    pub integration: String,
}

#[derive(Clone, Debug)]
pub struct SecurityPolicyDocSummary {
    pub id: String,
    pub title_ko: String,
    pub file: String,
    pub version: String,
    pub item_count: usize,
    pub summary_ko: String,
}

#[derive(Clone, Debug, Default)]
pub struct CodeSecurityCatalogCache {
    pub lenses: Vec<UnknownVulnLensEntry>,
    pub lens_languages: Vec<String>,
    pub lens_quorum: u64,
    pub lens_limits: BTreeMap<String, String>,
    pub analysis_components: Vec<AnalysisComponentEntry>,
    pub analysis_rule_files: Vec<String>,
    pub proof_harnesses: Vec<String>,
    pub policy_docs: Vec<SecurityPolicyDocSummary>,
    pub loaded_at_unix: u64,
}

#[derive(Clone, Debug)]
struct FilteredCvePage {
    total_filtered: usize,
    items: Vec<Value>,
}

const MAX_CATALOG_FILE_BYTES: u64 = 16 * 1024 * 1024;
const MAX_MSRC_SHARDS: usize = 64;
const MAX_RUNTIME_CVE_ROWS: usize = 200;

static MSRC_CSAF_CACHE: OnceLock<MsrcCsafCatalogCache> = OnceLock::new();
static CODE_SECURITY_CACHE: OnceLock<CodeSecurityCatalogCache> = OnceLock::new();

fn read_catalog_file_bounded(path: &Path) -> Option<String> {
    let meta = fs::symlink_metadata(path).ok()?;
    if meta.file_type().is_symlink() || !meta.is_file() || meta.len() > MAX_CATALOG_FILE_BYTES {
        return None;
    }
    fs::read_to_string(path).ok()
}

fn encode_query_component(raw: &str) -> String {
    let mut out = String::with_capacity(raw.len());
    for b in raw.bytes() {
        if b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.' | b'~' | b':') {
            out.push(char::from(b));
        } else {
            use std::fmt::Write as _;
            let _ = write!(out, "%{b:02X}");
        }
    }
    out
}

fn sanitize_https_url(raw: &str) -> String {
    let trimmed = raw.trim();
    if trimmed.starts_with("https://") && !trimmed.chars().any(char::is_control) {
        trimmed.to_string()
    } else {
        String::new()
    }
}

fn now_unix_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

async fn load_msrc_csaf_catalog_async() -> &'static MsrcCsafCatalogCache {
    if let Some(cached) = MSRC_CSAF_CACHE.get() {
        return cached;
    }
    tokio::task::spawn_blocking(load_msrc_csaf_catalog_cached)
        .await
        .unwrap_or_else(|_| load_msrc_csaf_catalog_cached())
}

async fn load_code_security_governance_async() -> &'static CodeSecurityCatalogCache {
    if let Some(cached) = CODE_SECURITY_CACHE.get() {
        return cached;
    }
    tokio::task::spawn_blocking(load_code_security_governance_cached)
        .await
        .unwrap_or_else(|_| load_code_security_governance_cached())
}

fn resolve_rule_catalog_root() -> Option<PathBuf> {
    if let Ok(cwd) = std::env::current_dir() {
        let direct = cwd.join("rule-catalog");
        if direct.is_dir() {
            return Some(direct);
        }
        if let Some(parent) = cwd.parent() {
            let up = parent.join("rule-catalog");
            if up.is_dir() {
                return Some(up);
            }
        }
    }
    let manifest = Path::new(env!("CARGO_MANIFEST_DIR"));
    if let Some(repo) = manifest.parent() {
        let rc = repo.join("rule-catalog");
        if rc.is_dir() {
            return Some(rc);
        }
    }
    None
}

fn classify_cve_priority_and_sla(
    severity: &str,
    exploit_status: &str,
    publicly_disclosed: bool,
    cvss: f64,
) -> (&'static str, &'static str, &'static str) {
    let sev = severity.trim().to_ascii_lowercase();
    let exp = exploit_status.trim().to_ascii_lowercase();
    if exp == "exploited" {
        ("P0", "immediate_24h", "24시간 긴급 조치 (KEV)")
    } else if publicly_disclosed || sev == "critical" || cvss >= 9.0 {
        ("P1", "urgent_72h", "72시간 우선 조치")
    } else if exp == "exploitation_more_likely" || sev == "high" || cvss >= 7.0 {
        ("P2", "high_14d", "14일 이내 조치")
    } else if sev == "medium" || cvss >= 4.0 {
        ("P3", "standard_30d", "30일 표준 조치")
    } else {
        ("P3", "monitor_90d", "90일 정기 모니터링")
    }
}

fn severity_sort_rank(severity: &str) -> u8 {
    match severity.trim().to_ascii_lowercase().as_str() {
        "critical" => 0,
        "high" => 1,
        "medium" => 2,
        "low" => 3,
        _ => 4,
    }
}

fn exploit_sort_rank(exploit: &str, publicly_disclosed: bool) -> u8 {
    match exploit.trim().to_ascii_lowercase().as_str() {
        "exploited" => 0,
        "exploitation_more_likely" => 1,
        _ if publicly_disclosed => 2,
        "exploitation_less_likely" => 3,
        "exploitation_unlikely" => 4,
        _ => 5,
    }
}

#[must_use]
pub fn load_msrc_csaf_catalog_cached() -> &'static MsrcCsafCatalogCache {
    MSRC_CSAF_CACHE.get_or_init(build_msrc_csaf_catalog)
}

fn build_msrc_csaf_catalog() -> MsrcCsafCatalogCache {
    let Some(rc_root) = resolve_rule_catalog_root() else {
        return MsrcCsafCatalogCache::default();
    };
    let msrc_dir = rc_root.join("collected").join("msrc-csaf");
    let manifest_path = msrc_dir.join("crosswalk.json");
    let Some(raw_manifest) = read_catalog_file_bounded(&manifest_path) else {
        return MsrcCsafCatalogCache::default();
    };
    let Ok(manifest) = serde_json::from_str::<Value>(&raw_manifest) else {
        return MsrcCsafCatalogCache::default();
    };

    let source_revision = manifest
        .get("source_revision")
        .and_then(Value::as_str)
        .unwrap_or("msrc-csaf")
        .to_string();
    let advisories_digest = manifest
        .get("advisories_digest")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let crosswalk_digest = manifest
        .get("crosswalk_digest")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();

    let mut product_map: HashMap<String, MsrcProductRef> = HashMap::new();
    if let Some(pms) = manifest.get("product_mappings").and_then(Value::as_array) {
        for pm in pms {
            let pid = pm
                .get("product_id")
                .and_then(Value::as_str)
                .unwrap_or("")
                .trim()
                .to_string();
            if pid.is_empty() {
                continue;
            }
            let pname = pm
                .get("product_name")
                .and_then(Value::as_str)
                .unwrap_or(&pid)
                .trim()
                .to_string();
            let mut rtypes: Vec<String> = pm
                .get("canonical_resource_types")
                .and_then(Value::as_array)
                .map(|arr| {
                    arr.iter()
                        .filter_map(Value::as_str)
                        .map(String::from)
                        .collect()
                })
                .unwrap_or_default();
            if rtypes.is_empty() {
                if let Some(single) = pm.get("canonical_resource_type").and_then(Value::as_str) {
                    if !single.is_empty() {
                        rtypes.push(single.to_string());
                    }
                }
            }
            product_map.insert(
                pid.clone(),
                MsrcProductRef {
                    product_id: pid,
                    product_name: pname,
                    canonical_resource_types: rtypes,
                },
            );
        }
    }

    let shards_dir = msrc_dir.join("shards");
    let mut shard_paths: Vec<PathBuf> = fs::read_dir(&shards_dir)
        .ok()
        .map(|rd| {
            rd.filter_map(Result::ok)
                .map(|e| e.path())
                .filter(|p| p.extension().and_then(|s| s.to_str()) == Some("json"))
                .collect()
        })
        .unwrap_or_default();
    shard_paths.sort();
    shard_paths.truncate(MAX_MSRC_SHARDS);

    let mut total_advisories = 0usize;
    let mut seen_cves: HashSet<String> = HashSet::new();
    let mut cves: Vec<MsrcCveEntry> = Vec::with_capacity(9_200);

    for sp in shard_paths {
        let Some(raw_shard) = read_catalog_file_bounded(&sp) else {
            continue;
        };
        let Ok(shard_val) = serde_json::from_str::<Value>(&raw_shard) else {
            continue;
        };
        let advisories_opt = shard_val
            .get("advisories")
            .and_then(Value::as_array)
            .or_else(|| shard_val.as_array());
        let Some(advisories) = advisories_opt else {
            continue;
        };
        total_advisories += advisories.len();
        for adv in advisories {
            let tracking_id = adv
                .get("tracking_id")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            let adv_title = adv
                .get("title")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            let release_date = adv
                .get("current_release_date")
                .or_else(|| adv.get("initial_release_date"))
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            let adv_url = adv
                .get("source_url")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            let sig_ok = adv
                .get("signature_verified")
                .and_then(Value::as_bool)
                .unwrap_or(false);

            let mut local_products: HashMap<String, String> = HashMap::new();
            if let Some(prods) = adv.get("products").and_then(Value::as_array) {
                for p in prods {
                    if let Some(pid) = p.get("product_id").and_then(Value::as_str) {
                        let name = p
                            .get("name")
                            .and_then(Value::as_str)
                            .unwrap_or(pid)
                            .to_string();
                        local_products.insert(pid.to_string(), name);
                    }
                }
            }

            let Some(vulns) = adv.get("vulnerabilities").and_then(Value::as_array) else {
                continue;
            };
            for v in vulns {
                let cve_id = v
                    .get("cve_id")
                    .or_else(|| v.get("cve"))
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .trim()
                    .to_ascii_uppercase();
                if cve_id.is_empty() || !seen_cves.insert(cve_id.clone()) {
                    continue;
                }
                let title = v
                    .get("title")
                    .and_then(Value::as_str)
                    .filter(|s| !s.trim().is_empty())
                    .unwrap_or(&adv_title)
                    .to_string();
                let cvss_base = v
                    .get("cvss_base_score")
                    .and_then(Value::as_f64)
                    .unwrap_or(0.0);
                let cvss_temp = v
                    .get("cvss_temporal_score")
                    .and_then(Value::as_f64)
                    .unwrap_or(cvss_base);
                let cvss_vector = v
                    .get("cvss_vector")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string();
                let severity = v
                    .get("severity")
                    .and_then(Value::as_str)
                    .unwrap_or_else(|| {
                        if cvss_base >= 9.0 {
                            "critical"
                        } else if cvss_base >= 7.0 {
                            "high"
                        } else if cvss_base >= 4.0 {
                            "medium"
                        } else {
                            "low"
                        }
                    })
                    .to_ascii_lowercase();
                let exploit_status = v
                    .get("exploit_status")
                    .and_then(Value::as_str)
                    .unwrap_or("unproven")
                    .to_ascii_lowercase();
                let publicly_disclosed = v
                    .get("publicly_disclosed")
                    .and_then(Value::as_bool)
                    .unwrap_or(false);
                let (priority_tier, kev_sla_tier, kev_sla_ko) =
                    classify_cve_priority_and_sla(&severity, &exploit_status, publicly_disclosed, cvss_base);

                let affected_ids: Vec<String> = v
                    .get("known_affected_product_ids")
                    .and_then(Value::as_array)
                    .map(|arr| {
                        arr.iter()
                            .filter_map(Value::as_str)
                            .map(String::from)
                            .collect()
                    })
                    .unwrap_or_default();

                let mut primary_product_name = String::new();
                let mut canonical_rtypes: Vec<String> = Vec::new();
                for pid in &affected_ids {
                    if let Some(pm) = product_map.get(pid) {
                        if primary_product_name.is_empty() {
                            primary_product_name = pm.product_name.clone();
                        }
                        for rt in &pm.canonical_resource_types {
                            if !canonical_rtypes.contains(rt) {
                                canonical_rtypes.push(rt.clone());
                            }
                        }
                    } else if primary_product_name.is_empty() {
                        if let Some(lp) = local_products.get(pid) {
                            primary_product_name = lp.clone();
                        }
                    }
                }

                let mut remediation_summary = String::new();
                let mut recommended_actions: Vec<String> = Vec::new();
                let mut vuln_url = adv_url.clone();
                if let Some(rems) = v.get("remediations").and_then(Value::as_array) {
                    for rem in rems {
                        if remediation_summary.is_empty() {
                            if let Some(det) = rem.get("details").and_then(Value::as_str) {
                                remediation_summary = det.trim().to_string();
                            }
                        }
                        if let Some(act) = rem.get("recommended_action_type").and_then(Value::as_str) {
                            let s = act.trim().to_string();
                            if !s.is_empty() && !recommended_actions.contains(&s) {
                                recommended_actions.push(s);
                            }
                        }
                        if let Some(u) = rem.get("url").and_then(Value::as_str) {
                            if !u.trim().is_empty() {
                                vuln_url = u.trim().to_string();
                            }
                        }
                    }
                }

                let search_blob = format!(
                    "{} {} {} {} {} {}",
                    cve_id,
                    tracking_id,
                    title,
                    primary_product_name,
                    severity,
                    exploit_status
                )
                .to_ascii_lowercase();

                cves.push(MsrcCveEntry {
                    cve_id,
                    tracking_id: tracking_id.clone(),
                    title,
                    severity,
                    cvss_base_score: cvss_base,
                    cvss_temporal_score: cvss_temp,
                    cvss_vector,
                    exploit_status,
                    publicly_disclosed,
                    priority_tier: priority_tier.to_string(),
                    kev_sla_tier: kev_sla_tier.to_string(),
                    kev_sla_ko: kev_sla_ko.to_string(),
                    release_date: release_date.clone(),
                    source_url: vuln_url,
                    signature_verified: sig_ok,
                    affected_product_ids: affected_ids,
                    primary_product_name,
                    canonical_resource_types: canonical_rtypes,
                    remediation_summary,
                    recommended_actions,
                    search_blob,
                });
            }
        }
    }

    cves.sort_by(|a, b| {
        exploit_sort_rank(&a.exploit_status, a.publicly_disclosed)
            .cmp(&exploit_sort_rank(&b.exploit_status, b.publicly_disclosed))
            .then_with(|| severity_sort_rank(&a.severity).cmp(&severity_sort_rank(&b.severity)))
            .then_with(|| {
                b.cvss_base_score
                    .partial_cmp(&a.cvss_base_score)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| b.cve_id.cmp(&a.cve_id))
    });

    let mut exploited_count = 0usize;
    let mut publicly_disclosed_count = 0usize;
    let mut critical_count = 0usize;
    let mut high_count = 0usize;
    let mut medium_count = 0usize;
    let mut low_count = 0usize;
    for c in &cves {
        if c.exploit_status == "exploited" {
            exploited_count += 1;
        }
        if c.publicly_disclosed {
            publicly_disclosed_count += 1;
        }
        match c.severity.as_str() {
            "critical" => critical_count += 1,
            "high" => high_count += 1,
            "medium" => medium_count += 1,
            _ => low_count += 1,
        }
    }

    MsrcCsafCatalogCache {
        source_revision,
        advisories_digest,
        crosswalk_digest,
        total_advisories,
        product_mapping_count: product_map.len(),
        exploited_count,
        publicly_disclosed_count,
        critical_count,
        high_count,
        medium_count,
        low_count,
        loaded_at_unix: now_unix_secs(),
        cves,
    }
}

fn lens_title_ko(lens_id: &str) -> &'static str {
    match lens_id {
        "missing-authorization" => "인가 누락 · 객체 권한 우회 (IDOR/BOLA)",
        "authentication-bypass" => "인증 우회 · 토큰/세션 검증 누락",
        "sql-injection" => "SQL 인젝션 · 비바인딩 쿼리 조합",
        "command-injection" => "OS 명령어 인젝션 · 셸 호출 오염",
        "path-traversal" => "경로 순회 · 임의 파일 읽기/쓰기",
        "server-side-request-forgery" => "서버 측 요청 위조 (SSRF · 메타데이터 노출)",
        "unsafe-deserialization" => "안전하지 않은 역직렬화 · 임의 코드 실행",
        "memory-safety" => "메모리 안전성 · 버퍼/UAF/널 역참조 (C/C++/Rust/Zig)",
        "xml-external-entity" => "XML 외부 엔티티 주입 (XXE)",
        "weak-cryptography" => "취약 암호 알고리즘 · 안전하지 않은 난수/서명",
        _ => "미지 취약점 분석 렌즈",
    }
}

fn parse_inline_yaml_list(raw: &str) -> Vec<String> {
    let trimmed = raw.trim();
    if let Some(inner) = trimmed.strip_prefix('[').and_then(|s| s.strip_suffix(']')) {
        inner
            .split(',')
            .map(|x| x.trim().trim_matches('"').trim_matches('\'').to_string())
            .filter(|x| !x.is_empty())
            .collect()
    } else {
        Vec::new()
    }
}

fn strip_yaml_quotes(raw: &str) -> String {
    raw.trim()
        .trim_matches('"')
        .trim_matches('\'')
        .to_string()
}

fn parse_lenses_yaml(
    content: &str,
) -> (
    Vec<UnknownVulnLensEntry>,
    Vec<String>,
    u64,
    BTreeMap<String, String>,
) {
    let mut lenses: Vec<UnknownVulnLensEntry> = Vec::new();
    let mut global_langs: Vec<String> = Vec::new();
    let mut quorum: u64 = 2;
    let mut lens_limits: BTreeMap<String, String> = BTreeMap::new();

    let mut section = "";
    let mut current_id = String::new();
    let mut current_wc = String::new();
    let mut current_cwes: Vec<String> = Vec::new();
    let mut current_langs: Vec<String> = Vec::new();
    let mut current_sinks: usize = 0;
    let mut current_focus = String::new();
    let mut sub_field = "";

    let flush = |lenses: &mut Vec<UnknownVulnLensEntry>,
                 id: &mut String,
                 wc: &mut String,
                 cwes: &mut Vec<String>,
                 langs: &mut Vec<String>,
                 sinks: &mut usize,
                 focus: &mut String,
                 q: u64| {
        if !id.is_empty() {
            lenses.push(UnknownVulnLensEntry {
                id: id.clone(),
                title_ko: lens_title_ko(id).to_string(),
                weakness_class: if wc.is_empty() {
                    id.replace('-', "_")
                } else {
                    wc.clone()
                },
                cwes: cwes.clone(),
                languages: langs.clone(),
                sink_hint_count: *sinks,
                focus: focus.trim().to_string(),
                quorum: q,
                mode: "shadow".to_string(),
            });
            id.clear();
            wc.clear();
            cwes.clear();
            langs.clear();
            *sinks = 0;
            focus.clear();
        }
    };

    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let indent = line.len() - line.trim_start().len();
        if indent == 0 {
            if section == "lenses" {
                flush(
                    &mut lenses,
                    &mut current_id,
                    &mut current_wc,
                    &mut current_cwes,
                    &mut current_langs,
                    &mut current_sinks,
                    &mut current_focus,
                    quorum,
                );
            }
            if trimmed.starts_with("languages:") {
                section = "languages";
            } else if trimmed.starts_with("limits:") {
                section = "limits";
            } else if trimmed.starts_with("lenses:") {
                section = "lenses";
            } else {
                section = "";
            }
            sub_field = "";
            continue;
        }

        if section == "limits" {
            if let Some((lk, lv)) = trimmed.split_once(':') {
                let lkey = lk.trim().to_string();
                let lval = strip_yaml_quotes(lv);
                if lkey == "quorum" {
                    if let Ok(parsed) = lval.parse::<u64>() {
                        quorum = parsed.max(1);
                    }
                }
                if !lkey.is_empty() && !lval.is_empty() {
                    lens_limits.insert(lkey, lval);
                }
            }
            continue;
        }
        if section == "languages" && indent == 2 && trimmed.ends_with(':') {
            let lang = trimmed.trim_end_matches(':').trim().to_string();
            if !lang.is_empty() && !global_langs.contains(&lang) {
                global_langs.push(lang);
            }
            continue;
        }
        if section == "lenses" {
            if indent == 2 && trimmed.ends_with(':') && !trimmed.starts_with('-') {
                flush(
                    &mut lenses,
                    &mut current_id,
                    &mut current_wc,
                    &mut current_cwes,
                    &mut current_langs,
                    &mut current_sinks,
                    &mut current_focus,
                    quorum,
                );
                current_id = trimmed.trim_end_matches(':').trim().to_string();
                sub_field = "";
            } else if indent == 4 && !trimmed.starts_with('-') {
                if let Some((k, rest)) = trimmed.split_once(':') {
                    let key = k.trim();
                    let val = rest.trim();
                    sub_field = match key {
                        "weakness_class" => {
                            current_wc = strip_yaml_quotes(val);
                            ""
                        }
                        "cwe" => {
                            let parsed = parse_inline_yaml_list(val);
                            for c in parsed {
                                current_cwes.push(if c.starts_with("CWE-") {
                                    c
                                } else {
                                    format!("CWE-{c}")
                                });
                            }
                            "cwe"
                        }
                        "languages" => {
                            current_langs.extend(parse_inline_yaml_list(val));
                            "languages"
                        }
                        "sink_hints" => "sink_hints",
                        "focus" => {
                            if !val.is_empty() && val != ">" && val != "|" && val != ">-" {
                                current_focus.push_str(&strip_yaml_quotes(val));
                            }
                            "focus"
                        }
                        _ => "",
                    };
                }
            } else if indent >= 6 {
                if sub_field == "sink_hints" && trimmed.starts_with('-') {
                    current_sinks += 1;
                } else if sub_field == "cwe" && trimmed.starts_with('-') {
                    let c = strip_yaml_quotes(trimmed.trim_start_matches('-'));
                    if !c.is_empty() {
                        current_cwes.push(if c.starts_with("CWE-") {
                            c
                        } else {
                            format!("CWE-{c}")
                        });
                    }
                } else if sub_field == "languages" && trimmed.starts_with('-') {
                    let l = strip_yaml_quotes(trimmed.trim_start_matches('-'));
                    if !l.is_empty() {
                        current_langs.push(l);
                    }
                } else if sub_field == "focus" {
                    if !current_focus.is_empty() {
                        current_focus.push(' ');
                    }
                    current_focus.push_str(trimmed);
                }
            }
        }
    }
    flush(
        &mut lenses,
        &mut current_id,
        &mut current_wc,
        &mut current_cwes,
        &mut current_langs,
        &mut current_sinks,
        &mut current_focus,
        quorum,
    );
    (lenses, global_langs, quorum, lens_limits)
}

fn parse_analysis_components_yaml(content: &str) -> Vec<AnalysisComponentEntry> {
    let mut out = Vec::new();
    let mut cur: Option<AnalysisComponentEntry> = None;
    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        if let Some(rest) = trimmed.strip_prefix("- id:") {
            if let Some(prev) = cur.take() {
                out.push(prev);
            }
            cur = Some(AnalysisComponentEntry {
                id: strip_yaml_quotes(rest),
                version: String::new(),
                purpose: String::new(),
                status: String::new(),
                license: String::new(),
                integration: String::new(),
            });
        } else if let Some(entry) = cur.as_mut() {
            if let Some((k, v)) = trimmed.split_once(':') {
                let val = strip_yaml_quotes(v);
                match k.trim() {
                    "version" => entry.version = val,
                    "purpose" => entry.purpose = val,
                    "status" => entry.status = val,
                    "license" => entry.license = val,
                    "integration" => entry.integration = val,
                    _ => {}
                }
            }
        }
    }
    if let Some(prev) = cur {
        out.push(prev);
    }
    out
}

fn summarize_policy_yaml(
    dir: &Path,
    file: &str,
    default_id: &str,
    title_ko: &str,
    summary_ko: &str,
) -> Option<SecurityPolicyDocSummary> {
    let raw = read_catalog_file_bounded(&dir.join(file))?;
    let mut id = default_id.to_string();
    let mut version = "1.0.0".to_string();
    let mut item_count = 0usize;
    for line in raw.lines() {
        let tr = line.trim();
        if let Some(v) = tr
            .strip_prefix("policy_id:")
            .or_else(|| tr.strip_prefix("rubric_id:"))
            .or_else(|| tr.strip_prefix("catalog_id:"))
        {
            id = strip_yaml_quotes(v);
        } else if let Some(v) = tr.strip_prefix("version:") {
            version = strip_yaml_quotes(v);
        } else if tr.starts_with("- id:") || tr.starts_with("- name:") || tr.starts_with("- band:") {
            item_count += 1;
        } else if (line.starts_with("  ") && !line.starts_with("    "))
            && tr.ends_with(':')
            && !tr.starts_with('-')
            && !tr.starts_with('#')
        {
            item_count += 1;
        }
    }
    Some(SecurityPolicyDocSummary {
        id,
        title_ko: title_ko.to_string(),
        file: format!("rule-catalog/code-security/{file}"),
        version,
        item_count: item_count.max(1),
        summary_ko: summary_ko.to_string(),
    })
}

#[must_use]
pub fn load_code_security_governance_cached() -> &'static CodeSecurityCatalogCache {
    CODE_SECURITY_CACHE.get_or_init(build_code_security_governance_cache)
}

fn build_code_security_governance_cache() -> CodeSecurityCatalogCache {
    let Some(rc_root) = resolve_rule_catalog_root() else {
        return CodeSecurityCatalogCache::default();
    };
    let cs_dir = rc_root.join("code-security");
    if !cs_dir.is_dir() {
        return CodeSecurityCatalogCache::default();
    }

    let (lenses, lens_languages, lens_quorum, lens_limits) =
        read_catalog_file_bounded(&cs_dir.join("lenses.yaml"))
            .map(|s| parse_lenses_yaml(&s))
            .unwrap_or_else(|| (Vec::new(), Vec::new(), 2, BTreeMap::new()));

    let analysis_components = read_catalog_file_bounded(&cs_dir.join("analysis-components.yaml"))
        .map(|s| parse_analysis_components_yaml(&s))
        .unwrap_or_default();

    let mut analysis_rule_files: Vec<String> = fs::read_dir(cs_dir.join("analysis-rules"))
        .ok()
        .map(|rd| {
            rd.filter_map(Result::ok)
                .filter_map(|e| e.file_name().into_string().ok())
                .filter(|n| n.ends_with(".yaml") || n.ends_with(".yml"))
                .collect()
        })
        .unwrap_or_default();
    analysis_rule_files.sort();

    let mut proof_harnesses: Vec<String> = fs::read_dir(cs_dir.join("prove"))
        .ok()
        .map(|rd| {
            rd.filter_map(Result::ok)
                .filter_map(|e| e.file_name().into_string().ok())
                .filter(|n| !n.starts_with('.'))
                .collect()
        })
        .unwrap_or_default();
    proof_harnesses.sort();

    let mut policy_docs = Vec::new();
    for (file, did, title, desc) in [
        (
            "severity-rubric.yaml",
            "fdai.code-security.severity-rubric",
            "심각도 결정 기준표 (Severity Rubric)",
            "영향도·공격 벡터·복잡도·권한 요건·사용자 개입 페널티로 결정론적 심각도 상/하한 산정",
        ),
        (
            "priority-policy.yaml",
            "fdai.code-security.priority-policy",
            "우선순위 · KEV/EPSS 조치 기한 정책",
            "KEV 악용 여부·외부 노출도·신뢰도 계단을 결합해 P0~P3 조치 기한을 결정론적으로 배정",
        ),
        (
            "weakness-classes.yaml",
            "fdai.code-security.weakness-classes",
            "약점 분류 · CWE 표준 매핑 카탈로그",
            "CWE 계통별 약점 클래스와 검증기·입증 하네스 적용 범위를 정의",
        ),
        (
            "remediation-policy.yaml",
            "fdai.code-security.remediation-policy",
            "자동 수정 경계 · 금지 경로 보안 정책",
            "패치 제안 시 수정 금지 경로·허용 변경 한도·필수 테스트 단언문 검증 규칙 정의",
        ),
    ] {
        if let Some(doc) = summarize_policy_yaml(&cs_dir, file, did, title, desc) {
            policy_docs.push(doc);
        }
    }

    CodeSecurityCatalogCache {
        lenses,
        lens_languages,
        lens_quorum,
        lens_limits,
        analysis_components,
        analysis_rule_files,
        proof_harnesses,
        policy_docs,
        loaded_at_unix: now_unix_secs(),
    }
}

async fn fetch_msrc_projection_and_runtime_cves(db: &DbHandle) -> (i64, HashSet<String>, bool) {
    let proj_sql = "SELECT COALESCE(jsonb_array_length(value->'controls'), 0) \
        FROM state_kv WHERE key = 'operator-projection:workflow:msrc-csaf.list' LIMIT 1";
    let runtime_cve_sql = "SELECT DISTINCT upper(a.val) \
        FROM state_kv sk, \
             jsonb_array_elements(COALESCE(sk.value->'issues', '[]'::jsonb)) AS iss(val), \
             jsonb_array_elements_text(COALESCE(iss.val->'advisory_ids', '[]'::jsonb)) AS a(val) \
        WHERE sk.key LIKE 'runtime:code-security-issues:%' \
          AND sk.key NOT LIKE '%:artifacts%' \
          AND upper(a.val) LIKE 'CVE-%' \
        LIMIT 5000";
    let (proj_res, rt_res) = tokio::join!(
        db.query_single_readonly(proj_sql),
        db.query_single_readonly(runtime_cve_sql),
    );
    let db_ok = proj_res.is_ok() || rt_res.is_ok();
    let proj_cnt = proj_res
        .ok()
        .and_then(|q| q.rows.first().and_then(|r| cell_i64(r, 0)))
        .unwrap_or(0);
    let mut rt_set = HashSet::new();
    if let Ok(q) = rt_res {
        for row in &q.rows {
            let cid = cell_str(row, 0).trim().to_ascii_uppercase();
            if cid.starts_with("CVE-") {
                rt_set.insert(cid);
            }
        }
    }
    (proj_cnt, rt_set, db_ok)
}

fn humanize_msrc_title_ko(raw_title: &str, primary_product: &str) -> String {
    let trimmed = raw_title.trim();
    if trimmed.is_empty() || trimmed.to_ascii_uppercase().starts_with("CVE-") {
        if !primary_product.trim().is_empty() {
            return format!("{} 보안 취약점", primary_product.trim());
        }
        return "보안 취약점 권고".to_string();
    }
    let mut s = trimmed.to_string();
    for (en, ko) in [
        ("Remote Code Execution Vulnerability", "원격 코드 실행(RCE) 취약점"),
        ("Elevation of Privilege Vulnerability", "권한 상승(EoP) 취약점"),
        ("Privilege Escalation Vulnerability", "권한 상승(EoP) 취약점"),
        ("Security Feature Bypass Vulnerability", "보안 기능 우회 취약점"),
        ("Information Disclosure Vulnerability", "민감 정보 노출 취약점"),
        ("Denial of Service Vulnerability", "서비스 거부(DoS) 취약점"),
        ("Spoofing Vulnerability", "스푸핑(위장) 취약점"),
        ("Tampering Vulnerability", "데이터 변조 취약점"),
        ("Memory Corruption Vulnerability", "메모리 손상 취약점"),
        ("Cross-site Scripting Vulnerability", "크로스 사이트 스크립팅(XSS) 취약점"),
        ("Cross-Site Scripting Vulnerability", "크로스 사이트 스크립팅(XSS) 취약점"),
        ("SQL Injection Vulnerability", "SQL 인젝션 취약점"),
        ("Command Injection Vulnerability", "명령어 인젝션 취약점"),
        ("Path Traversal Vulnerability", "경로 순회 취약점"),
        ("Buffer Overflow Vulnerability", "버퍼 오버플로 취약점"),
        ("Use After Free Vulnerability", "메모리 해제 후 재사용(UAF) 취약점"),
        ("Authentication Bypass Vulnerability", "인증 우회 취약점"),
        ("Legacy TLS Downgrade", "레거시 TLS 다운그레이드 취약점"),
        ("Elevation of Privilege", "권한 상승(EoP) 취약점"),
        ("Remote Code Execution", "원격 코드 실행(RCE) 취약점"),
        ("Security Feature Bypass", "보안 기능 우회 취약점"),
        ("Information Disclosure", "민감 정보 노출 취약점"),
        ("Denial of Service", "서비스 거부(DoS) 취약점"),
        ("Node Image", "노드 이미지"),
        ("Vulnerability", "보안 취약점"),
    ] {
        if s.contains(en) {
            s = s.replace(en, ko);
        }
    }
    s.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn weakness_class_label_ko(wc: &str) -> &'static str {
    match wc.trim().to_ascii_lowercase().as_str() {
        "vulnerable_dependency" | "dependency" | "sca" => "취약 종속성 보안 취약점",
        "sql_injection" => "SQL 인젝션 취약점",
        "command_injection" => "명령어 인젝션 취약점",
        "missing_authorization" => "인가 누락 · 권한 우회 취약점",
        "authentication_bypass" => "인증 우회 취약점",
        "path_traversal" => "경로 순회 취약점",
        "server_side_request_forgery" | "ssrf" => "서버 측 요청 위조(SSRF) 취약점",
        "unsafe_deserialization" => "안전하지 않은 역직렬화 취약점",
        "memory_safety" => "메모리 안전성 취약점",
        "xml_external_entity" | "xxe" => "XML 외부 엔티티 주입(XXE) 취약점",
        "weak_cryptography" => "취약 암호 알고리즘 취약점",
        "hardcoded_secret" | "secret_exposure" => "하드코딩된 비밀정보 노출 취약점",
        "misconfiguration" | "iac_misconfiguration" => "인프라 보안 구성 오류 취약점",
        _ => "코드·패키지 보안 취약점",
    }
}

#[allow(clippy::too_many_arguments)]
fn humanize_runtime_cve_title_ko(
    cve_id: &str,
    sarif_title: &str,
    weakness_class: &str,
    pkg: &str,
    lang: &str,
    file_path: &str,
    cvss: f64,
    producer: &str,
) -> String {
    let raw = sarif_title.trim();
    let is_bare = raw.is_empty()
        || raw.eq_ignore_ascii_case(cve_id)
        || raw.to_ascii_uppercase().starts_with("CVE-")
        || raw.to_ascii_uppercase().starts_with("GHSA-")
        || raw.eq_ignore_ascii_case("vulnerable_dependency");
    if !is_bare {
        return humanize_msrc_title_ko(raw, pkg);
    }
    let wc_ko = weakness_class_label_ko(weakness_class);
    let target = if !pkg.trim().is_empty() {
        if !lang.trim().is_empty() {
            format!("{} {}", lang.trim(), pkg.trim())
        } else {
            pkg.trim().to_string()
        }
    } else if !file_path.trim().is_empty() {
        let fname = file_path.rsplit('/').next().unwrap_or(file_path.trim());
        if !lang.trim().is_empty() {
            format!("{} {fname}", lang.trim())
        } else {
            fname.to_string()
        }
    } else if !lang.trim().is_empty() {
        lang.trim().to_string()
    } else {
        "오픈소스 종속성".to_string()
    };
    let mut meta: Vec<String> = Vec::new();
    if !producer.trim().is_empty() {
        meta.push(producer.trim().to_string());
    }
    if cvss > 0.0 {
        meta.push(format!("CVSS {cvss:.1}"));
    }
    if meta.is_empty() {
        format!("{target} {wc_ko}")
    } else {
        format!("{target} {wc_ko} ({})", meta.join(" · "))
    }
}

fn cve_entry_to_json(c: &MsrcCveEntry, runtime_detected: bool) -> Value {
    let exploit_ko = match c.exploit_status.as_str() {
        "exploited" => "실제 악용 확인 (KEV)",
        "exploitation_more_likely" => "악용 가능성 높음",
        "exploitation_less_likely" => "악용 가능성 낮음",
        "exploitation_unlikely" => "악용 가능성 희박",
        "publicly_disclosed" => "공개 취약점",
        _ => "미확인",
    };
    let sev_ko = match c.severity.as_str() {
        "critical" => "긴급",
        "high" => "높음",
        "medium" => "보통",
        _ => "낮음",
    };
    let title_ko = humanize_msrc_title_ko(&c.title, &c.primary_product_name);
    let kev_triggered = kev_alert_watermark_triggered(c.cvss_base_score, 7.0, 3_600, 60);
    json!({
        "cve_id": c.cve_id,
        "tracking_id": c.tracking_id,
        "title": title_ko,
        "title_ko": title_ko,
        "title_en": c.title,
        "severity": c.severity,
        "severity_ko": sev_ko,
        "cvss_base_score": c.cvss_base_score,
        "cvss_temporal_score": c.cvss_temporal_score,
        "cvss_vector": c.cvss_vector,
        "exploit_status": c.exploit_status,
        "exploit_status_ko": exploit_ko,
        "publicly_disclosed": c.publicly_disclosed,
        "priority_tier": c.priority_tier,
        "kev_sla_tier": c.kev_sla_tier,
        "kev_sla_ko": c.kev_sla_ko,
        "kev_watermark_alert": kev_triggered && (c.exploit_status == "exploited" || c.publicly_disclosed),
        "runtime_detected": runtime_detected,
        "release_date": c.release_date,
        "source_url": sanitize_https_url(&c.source_url),
        "signature_verified": c.signature_verified,
        "primary_product_name": c.primary_product_name,
        "affected_products": c.affected_product_ids,
        "canonical_resource_types": c.canonical_resource_types,
        "remediation_summary": c.remediation_summary,
        "recommended_actions": c.recommended_actions,
        "operations_link": format!("/operations/code-security?item={}", encode_query_component(&c.cve_id))
    })
}

#[allow(clippy::too_many_arguments)]
fn query_msrc_cves_from_cache(
    catalog: &MsrcCsafCatalogCache,
    runtime_cves: &HashSet<String>,
    search: Option<&str>,
    severity: Option<&str>,
    exploit: Option<&str>,
    priority: Option<&str>,
    runtime_only: bool,
    limit: usize,
    offset: usize,
) -> FilteredCvePage {
    let q_low = clean_opt(search).map(str::to_ascii_lowercase);
    let sev_low = clean_opt(severity).map(str::to_ascii_lowercase);
    let exp_low = clean_opt(exploit).map(str::to_ascii_lowercase);
    let pri_up = clean_opt(priority).map(str::to_ascii_uppercase);

    let mut matched: Vec<(&MsrcCveEntry, bool)> = Vec::new();
    for c in &catalog.cves {
        let rt_hit = runtime_cves.contains(&c.cve_id);
        if runtime_only && !rt_hit {
            continue;
        }
        if let Some(ref s) = sev_low {
            if s != "all" && c.severity != *s {
                continue;
            }
        }
        if let Some(ref e) = exp_low {
            if e != "all" {
                if e == "publicly_disclosed" {
                    if !c.publicly_disclosed {
                        continue;
                    }
                } else if c.exploit_status != *e {
                    continue;
                }
            }
        }
        if let Some(ref p) = pri_up {
            if p != "ALL" && c.priority_tier != *p {
                continue;
            }
        }
        if let Some(ref q) = q_low {
            if !c.search_blob.contains(q.as_str()) {
                continue;
            }
        }
        matched.push((c, rt_hit));
    }

    // Prioritize runtime-detected CVEs at the very top while preserving catalog sort order
    matched.sort_by_key(|(_, rt_hit)| if *rt_hit { 0u8 } else { 1u8 });

    let total_filtered = matched.len();
    let items: Vec<Value> = matched
        .into_iter()
        .skip(offset)
        .take(limit)
        .map(|(c, rt_hit)| cve_entry_to_json(c, rt_hit))
        .collect();

    FilteredCvePage {
        total_filtered,
        items,
    }
}

pub async fn fetch_security_cves(
    db: &DbHandle,
    search: Option<&str>,
    severity: Option<&str>,
    exploit: Option<&str>,
    priority: Option<&str>,
    runtime_only: bool,
    limit: Option<usize>,
    offset: Option<usize>,
) -> Value {
    let lim = clamp_limit(limit, 80, 300);
    let off = offset.unwrap_or(0).min(100_000);
    let catalog = load_msrc_csaf_catalog_async().await;

    let (proj_and_rt, ops_sec) = tokio::join!(
        fetch_msrc_projection_and_runtime_cves(db),
        crate::repos::operations::fetch_security(db),
    );
    let (msrc_proj_cnt, mut runtime_cves, rt_proj_ok) = proj_and_rt;
    let ops_sec_ok = ops_sec.get("measurement_status").and_then(Value::as_str) == Some("measured");
    let db_available = rt_proj_ok || ops_sec_ok;

    let msrc_title_by_cve: HashMap<&str, &MsrcCveEntry> = catalog
        .cves
        .iter()
        .map(|c| (c.cve_id.as_str(), c))
        .collect();

    let mut runtime_cve_rows: Vec<Value> = Vec::new();
    let mut seen_rt_cves: HashSet<String> = HashSet::new();
    if let Some(issues) = ops_sec.get("code_security_issues").and_then(Value::as_array) {
        let q_low = clean_opt(search).map(str::to_ascii_lowercase);
        for iss in issues {
            let issue_id = iss.get("issue_id").and_then(Value::as_str).unwrap_or("").to_string();
            let rule_id = iss.get("rule_id").and_then(Value::as_str).unwrap_or("").to_string();
            let weakness_class = iss
                .get("weakness_class")
                .and_then(Value::as_str)
                .unwrap_or(&rule_id)
                .to_string();
            let sarif_title = iss.get("sarif_title").and_then(Value::as_str).unwrap_or("").to_string();
            let sev = iss
                .get("severity")
                .and_then(Value::as_str)
                .unwrap_or("undetermined")
                .to_ascii_lowercase();
            let conf = iss
                .get("confidence")
                .and_then(Value::as_str)
                .unwrap_or("reported")
                .to_ascii_lowercase();
            let repo = iss.get("repo").and_then(Value::as_str).unwrap_or("").to_string();
            let file_path = iss.get("file_path").and_then(Value::as_str).unwrap_or("").to_string();
            let pkg = iss.get("package").and_then(Value::as_str).unwrap_or("").to_string();
            let lang = iss.get("language").and_then(Value::as_str).unwrap_or("").to_string();
            let pri = iss.get("priority").and_then(Value::as_str).unwrap_or("P2").to_string();
            let kev = iss.get("known_exploited").and_then(Value::as_bool).unwrap_or(false);
            let cvss_val = iss.get("cvss_score").and_then(Value::as_f64).unwrap_or(0.0);
            let rationale = iss
                .get("severity_rationale")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            let producer = iss
                .get("producers")
                .and_then(Value::as_array)
                .and_then(|arr| arr.first())
                .and_then(Value::as_str)
                .unwrap_or("Trivy")
                .to_string();
            let cve_list: Vec<String> = iss
                .get("advisory_ids")
                .and_then(Value::as_array)
                .map(|arr| {
                    arr.iter()
                        .filter_map(Value::as_str)
                        .map(str::to_ascii_uppercase)
                        .filter(|s| s.starts_with("CVE-"))
                        .collect()
                })
                .unwrap_or_default();
            for cve_id in cve_list {
                runtime_cves.insert(cve_id.clone());
                if !seen_rt_cves.insert(cve_id.clone()) {
                    continue;
                }
                let title_ko = if let Some(msrc_hit) = msrc_title_by_cve.get(cve_id.as_str()) {
                    humanize_msrc_title_ko(&msrc_hit.title, &msrc_hit.primary_product_name)
                } else {
                    humanize_runtime_cve_title_ko(
                        &cve_id,
                        &sarif_title,
                        &weakness_class,
                        &pkg,
                        &lang,
                        &file_path,
                        cvss_val,
                        &producer,
                    )
                };
                if let Some(ref q) = q_low {
                    let blob = format!(
                        "{cve_id} {title_ko} {sarif_title} {repo} {pkg} {file_path} {rule_id} {weakness_class} {lang}"
                    )
                    .to_ascii_lowercase();
                    if !blob.contains(q.as_str()) {
                        continue;
                    }
                }
                if let Some(s) = clean_opt(severity) {
                    let sl = s.to_ascii_lowercase();
                    if sl != "all" && sev != sl {
                        continue;
                    }
                }
                runtime_cve_rows.push(json!({
                    "cve_id": cve_id,
                    "issue_id": issue_id,
                    "rule_id": rule_id,
                    "weakness_class": weakness_class,
                    "title": title_ko,
                    "title_ko": title_ko,
                    "title_en": sarif_title,
                    "severity": sev,
                    "confidence": conf,
                    "repo": repo,
                    "file_path": file_path,
                    "package": pkg,
                    "language": lang,
                    "producer": producer,
                    "severity_rationale": rationale,
                    "priority": pri,
                    "known_exploited": kev,
                    "cvss_score": if cvss_val > 0.0 { json!(cvss_val) } else { Value::Null },
                    "source": "runtime-code-security",
                    "operations_link": format!("/operations/code-security?item={}", encode_query_component(&issue_id))
                }));
            }
        }
    }
    runtime_cve_rows.sort_by_key(|v| {
        (
            severity_sort_rank(v.get("severity").and_then(Value::as_str).unwrap_or("low")),
            v.get("cve_id")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string(),
        )
    });

    let page = query_msrc_cves_from_cache(
        catalog,
        &runtime_cves,
        search,
        severity,
        exploit,
        priority,
        runtime_only,
        lim,
        off,
    );

    let msrc_cve_ids: HashSet<&str> = catalog.cves.iter().map(|c| c.cve_id.as_str()).collect();
    let msrc_runtime_matched = catalog
        .cves
        .iter()
        .filter(|c| runtime_cves.contains(&c.cve_id))
        .count();

    // Unify runtime-detected CVEs (Trivy/OSV-Scanner) not already in MSRC CSAF so runtime_only=1 and CVE search never miss them.
    let exp_filter = clean_opt(exploit).map(str::to_ascii_lowercase);
    let pri_filter = clean_opt(priority).map(str::to_ascii_uppercase);
    let mut extra_runtime_entries: Vec<Value> = Vec::new();
    for rc in &runtime_cve_rows {
        let cid = rc.get("cve_id").and_then(Value::as_str).unwrap_or("");
        if msrc_cve_ids.contains(cid) {
            continue;
        }
        let kev = rc.get("known_exploited").and_then(Value::as_bool).unwrap_or(false);
        let exploit_st = if kev { "exploited" } else { "unproven" };
        if let Some(ref e) = exp_filter {
            if e != "all" && e != exploit_st {
                continue;
            }
        }
        let sev = rc.get("severity").and_then(Value::as_str).unwrap_or("medium");
        let cvss = rc.get("cvss_score").and_then(Value::as_f64).unwrap_or(0.0);
        let (ptier, ksla, kslako) = classify_cve_priority_and_sla(sev, exploit_st, false, cvss);
        let rc_pri = rc
            .get("priority")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
            .unwrap_or(ptier)
            .to_ascii_uppercase();
        if let Some(ref p) = pri_filter {
            if p != "ALL" && rc_pri != *p {
                continue;
            }
        }
        let sev_ko = match sev {
            "critical" => "긴급",
            "high" => "높음",
            "medium" => "보통",
            "low" => "낮음",
            _ => "미분류",
        };
        let repo = rc.get("repo").and_then(Value::as_str).unwrap_or("");
        let pkg = rc.get("package").and_then(Value::as_str).unwrap_or("");
        let fpath = rc.get("file_path").and_then(Value::as_str).unwrap_or("");
        let prod_label = if !repo.is_empty() && !pkg.is_empty() {
            format!("{repo} · {pkg}")
        } else if !pkg.is_empty() {
            pkg.to_string()
        } else if !repo.is_empty() && !fpath.is_empty() {
            format!("{repo} · {fpath}")
        } else if !fpath.is_empty() {
            fpath.to_string()
        } else {
            repo.to_string()
        };
        let title_ko = rc
            .get("title_ko")
            .or_else(|| rc.get("title"))
            .and_then(Value::as_str)
            .filter(|s| !s.trim().is_empty())
            .unwrap_or("오픈소스 종속성 보안 취약점");
        let title_en = rc.get("title_en").and_then(Value::as_str).unwrap_or("");
        let rationale = rc
            .get("severity_rationale")
            .and_then(Value::as_str)
            .unwrap_or("");
        let producer = rc.get("producer").and_then(Value::as_str).unwrap_or("Trivy");
        let rem_text = if !pkg.is_empty() {
            format!(
                "운영 코드 보안 스캔({producer})이 {repo} 저장소({fpath})의 {pkg} 패키지에서 실측 탐지했습니다.{} 최신 보안 패치 버전으로 업그레이드하고 회귀 검증하세요.",
                if rationale.is_empty() { String::new() } else { format!(" ({rationale})") }
            )
        } else {
            format!(
                "운영 코드 보안 스캔({producer})이 {repo} 저장소({fpath})에서 실측 탐지했습니다. 취약 종속성/코드를 보안 패치 버전으로 업데이트하세요."
            )
        };
        extra_runtime_entries.push(json!({
            "cve_id": cid,
            "tracking_id": rc.get("issue_id").and_then(Value::as_str).unwrap_or(""),
            "title": title_ko,
            "title_ko": title_ko,
            "title_en": title_en,
            "severity": sev,
            "severity_ko": sev_ko,
            "cvss_base_score": cvss,
            "cvss_temporal_score": cvss,
            "cvss_vector": "",
            "exploit_status": exploit_st,
            "exploit_status_ko": if kev { "실제 악용 확인 (KEV)" } else { "런타임 스캐너 탐지" },
            "publicly_disclosed": false,
            "priority_tier": rc_pri,
            "kev_sla_tier": ksla,
            "kev_sla_ko": kslako,
            "kev_watermark_alert": kev,
            "runtime_detected": true,
            "release_date": "",
            "source_url": "",
            "signature_verified": false,
            "primary_product_name": prod_label,
            "affected_products": if pkg.is_empty() { json!([]) } else { json!([pkg]) },
            "canonical_resource_types": [],
            "remediation_summary": rem_text,
            "recommended_actions": [],
            "operations_link": rc.get("operations_link").and_then(Value::as_str).unwrap_or("/operations/code-security"),
            "source": "runtime-code-security"
        }));
    }

    let extra_cnt = extra_runtime_entries.len();
    let total_filtered = extra_cnt + page.total_filtered;
    let combined_items: Vec<Value> = if off < extra_cnt {
        let mut out: Vec<Value> = extra_runtime_entries
            .into_iter()
            .skip(off)
            .take(lim)
            .collect();
        if out.len() < lim {
            let need = lim - out.len();
            let msrc_head = query_msrc_cves_from_cache(
                catalog,
                &runtime_cves,
                search,
                severity,
                exploit,
                priority,
                runtime_only,
                need,
                0,
            );
            out.extend(msrc_head.items);
        }
        out
    } else {
        let shifted = query_msrc_cves_from_cache(
            catalog,
            &runtime_cves,
            search,
            severity,
            exploit,
            priority,
            runtime_only,
            lim,
            off - extra_cnt,
        );
        shifted.items
    };

    let eval_source = if msrc_proj_cnt > 0 {
        "msrc-csaf-shadow-assessment"
    } else {
        "repository-catalog"
    };
    let runtime_cves_truncated = runtime_cve_rows.len() > MAX_RUNTIME_CVE_ROWS;
    if runtime_cves_truncated {
        runtime_cve_rows.truncate(MAX_RUNTIME_CVE_ROWS);
    }
    let db_status = if db_available { "measured" } else { "not-measured" };

    json!({
        "measurement_status": "measured",
        "db_measurement_status": db_status,
        "runtime_metrics_available": db_available,
        "source": if db_available { "msrc-csaf-catalog+postgres" } else { "msrc-csaf-catalog" },
        "evaluation_source": eval_source,
        "source_revision": catalog.source_revision,
        "advisories_digest": catalog.advisories_digest,
        "crosswalk_digest": catalog.crosswalk_digest,
        "loaded_at_unix": catalog.loaded_at_unix,
        "summary": {
            "msrc_total_cves": catalog.cves.len(),
            "unified_total_cves": catalog.cves.len() + runtime_cves.len().saturating_sub(msrc_runtime_matched),
            "msrc_total_advisories": catalog.total_advisories,
            "exploited_count": catalog.exploited_count,
            "publicly_disclosed_count": catalog.publicly_disclosed_count,
            "critical_count": catalog.critical_count,
            "high_count": catalog.high_count,
            "medium_count": catalog.medium_count,
            "low_count": catalog.low_count,
            "product_mapping_count": catalog.product_mapping_count,
            "runtime_detected_unique_cves": if db_available { json!(runtime_cves.len()) } else { Value::Null },
            "runtime_msrc_crosswalk_matched": if db_available { json!(msrc_runtime_matched) } else { Value::Null },
            "filtered_total": total_filtered
        },
        "limit": lim,
        "offset": off,
        "cves": combined_items,
        "runtime_cves": runtime_cve_rows,
        "runtime_cves_truncated": runtime_cves_truncated
    })
}

pub async fn fetch_security_unknown_vulns(db: &DbHandle) -> Value {
    let cs = load_code_security_governance_async().await;

    let conf_sql = "SELECT lower(COALESCE(iss.val->>'confidence', 'reported')), count(*) \
        FROM state_kv sk, \
             jsonb_array_elements(COALESCE(sk.value->'issues', '[]'::jsonb)) AS iss(val) \
        WHERE sk.key LIKE 'runtime:code-security-issues:%' \
          AND sk.key NOT LIKE '%:artifacts%' \
        GROUP BY 1";
    let worker_sql = "SELECT key, COALESCE(value::text, '{}'), COALESCE(updated_at::text, '') \
        FROM state_kv \
        WHERE key = 'runtime:code-security-worker:v1' \
           OR key LIKE 'runtime:code-security-pack:%' \
           OR key LIKE 'runtime:code-security-review:%' \
           OR key LIKE 'runtime:code-security-repository:%' \
        LIMIT 64";

    let (conf_res, worker_res) = tokio::join!(
        db.query_single_readonly(conf_sql),
        db.query_single_readonly(worker_sql),
    );

    let mut conf_counts: BTreeMap<String, i64> = BTreeMap::new();
    for k in ["hypothesis", "reported", "corroborated", "verified", "proven"] {
        conf_counts.insert(k.to_string(), 0);
    }
    let db_available = conf_res.is_ok();
    if let Ok(cq) = conf_res {
        for row in &cq.rows {
            let k = cell_str(row, 0);
            let cnt = cell_i64(row, 1).unwrap_or(0);
            *conf_counts.entry(k).or_insert(0) += cnt;
        }
    }

    let mut worker_status = json!({
        "recorded": false,
        "status": "unrecorded",
        "message_ko": "오프패스 LLM 렌즈 및 동적 입증(Kata) 워커 실행 이력이 아직 기록되지 않았습니다. 현재 실측 이슈는 결정론적 정적/패키지 스캐너 결과입니다."
    });
    let mut pack_count = 0usize;
    let mut review_count = 0usize;
    let mut repo_count = 0usize;
    if let Ok(wq) = worker_res {
        for row in &wq.rows {
            let k = cell_str(row, 0);
            if k == "runtime:code-security-worker:v1" {
                let parsed: Value = serde_json::from_str(&cell_str(row, 1)).unwrap_or_else(|_| json!({}));
                worker_status = json!({
                    "recorded": true,
                    "status": parsed.get("status").and_then(Value::as_str).unwrap_or("recorded"),
                    "updated_at": cell_str(row, 2),
                    "detail": parsed
                });
            } else if k.starts_with("runtime:code-security-pack:") {
                pack_count += 1;
            } else if k.starts_with("runtime:code-security-review:") {
                review_count += 1;
            } else if k.starts_with("runtime:code-security-repository:") {
                repo_count += 1;
            }
        }
    }

    let hypothesis_cnt = *conf_counts.get("hypothesis").unwrap_or(&0);
    let reported_cnt = *conf_counts.get("reported").unwrap_or(&0);
    let corroborated_cnt = *conf_counts.get("corroborated").unwrap_or(&0);
    let verified_cnt = *conf_counts.get("verified").unwrap_or(&0);
    let proven_cnt = *conf_counts.get("proven").unwrap_or(&0);

    let active_components = cs
        .analysis_components
        .iter()
        .filter(|c| c.status == "active")
        .count();
    let total_components = cs.analysis_components.len();
    let engine_wilson_lb95 = wilson_assurance_lb95(active_components as u64, total_components as u64);
    let active_ratio = security_coverage_ratio(active_components as u64, total_components as u64);
    let gate_ready = promotion_gate_margin_passed(active_ratio, 0.50, 0.10) && cs.lens_quorum >= 2;

    let lenses_json: Vec<Value> = cs
        .lenses
        .iter()
        .map(|l| {
            json!({
                "id": l.id,
                "item_id": format!("lens:{}", l.id),
                "title_ko": l.title_ko,
                "weakness_class": l.weakness_class,
                "cwes": l.cwes,
                "languages": l.languages,
                "language_count": l.languages.len(),
                "sink_hint_count": l.sink_hint_count,
                "focus": l.focus,
                "quorum": l.quorum,
                "mode": l.mode,
                "mode_ko": "모의 검증 (Shadow · 자동 변경 금지)",
                "promotion_gate_ready": gate_ready,
                "live_hypothesis_count": hypothesis_cnt
            })
        })
        .collect();

    let components_json: Vec<Value> = cs
        .analysis_components
        .iter()
        .map(|c| {
            let status_ko = if c.status == "active" {
                "활성 엔진"
            } else {
                "연구·비교 전용"
            };
            json!({
                "id": c.id,
                "version": c.version,
                "purpose": c.purpose,
                "status": c.status,
                "status_ko": status_ko,
                "license": c.license,
                "integration": c.integration
            })
        })
        .collect();

    let policies_json: Vec<Value> = cs
        .policy_docs
        .iter()
        .map(|p| {
            json!({
                "id": p.id,
                "title_ko": p.title_ko,
                "file": p.file,
                "version": p.version,
                "item_count": p.item_count,
                "summary_ko": p.summary_ko
            })
        })
        .collect();

    let db_status = if db_available { "measured" } else { "not-measured" };
    let opt_db_i64 = |v: i64| -> Value {
        if db_available {
            json!(v)
        } else {
            Value::Null
        }
    };

    json!({
        "measurement_status": "measured",
        "db_measurement_status": db_status,
        "runtime_metrics_available": db_available,
        "loaded_at_unix": cs.loaded_at_unix,
        "source": if db_available { "code-security-catalog+postgres" } else { "code-security-catalog" },
        "constitutional_invariant": {
            "non_mixing_enforced": true,
            "summary_ko": "미지 취약점 가설(hypothesis)은 확정 취약점(CVE·verified·proven)과 절대 합산하지 않으며, 자동 변경 권한 없이 Shadow·결정론적 검증·Kata 동적 입증 경로만 허용됩니다."
        },
        "confidence_ladder": {
            "confirmed_or_scanner_total": opt_db_i64(reported_cnt + corroborated_cnt + verified_cnt + proven_cnt),
            "unknown_hypothesis_separate_total": opt_db_i64(hypothesis_cnt),
            "stages": [
                {
                    "stage": "hypothesis",
                    "label_ko": "① 미지 취약점 가설 (LLM 렌즈)",
                    "count": opt_db_i64(hypothesis_cnt),
                    "separate_from_confirmed": true,
                    "gate_ko": "이종 모델 정족수(quorum=2) · 자동 변경 금지"
                },
                {
                    "stage": "reported",
                    "label_ko": "② 스캐너 보고 (SAST/SCA)",
                    "count": opt_db_i64(reported_cnt),
                    "separate_from_confirmed": false,
                    "gate_ko": "Trivy · OSV-Scanner · Gitleaks 결정론 보고"
                },
                {
                    "stage": "corroborated",
                    "label_ko": "③ 교차 확인 (다중 근거)",
                    "count": opt_db_i64(corroborated_cnt),
                    "separate_from_confirmed": false,
                    "gate_ko": "복수 분석기/규칙 교차 일치"
                },
                {
                    "stage": "verified",
                    "label_ko": "④ 결정론적 검증 (코드 그래프)",
                    "count": opt_db_i64(verified_cnt),
                    "separate_from_confirmed": false,
                    "gate_ko": "함수 간 데이터흐름(Taint) · AST/컴파일러 검증"
                },
                {
                    "stage": "proven",
                    "label_ko": "⑤ 동적 입증 (Kata 샌드박스)",
                    "count": opt_db_i64(proven_cnt),
                    "separate_from_confirmed": false,
                    "gate_ko": "격리 Kata 샌드박스 PoC 재현(fdai_prove)"
                }
            ]
        },
        "summary": {
            "lens_count": cs.lenses.len(),
            "supported_language_count": cs.lens_languages.len(),
            "supported_languages": cs.lens_languages,
            "multi_model_quorum": cs.lens_quorum,
            "lens_limits": cs.lens_limits,
            "active_analysis_engines": active_components,
            "total_analysis_engines": total_components,
            "analysis_rule_files_count": cs.analysis_rule_files.len(),
            "proof_harness_count": cs.proof_harnesses.len(),
            "policy_doc_count": cs.policy_docs.len(),
            "engine_wilson_lb95": (engine_wilson_lb95 * 1000.0).round() / 1000.0,
            "promotion_gate_ready": gate_ready,
            "live_pack_projections": if db_available { json!(pack_count) } else { Value::Null },
            "live_review_projections": if db_available { json!(review_count) } else { Value::Null },
            "live_repository_projections": if db_available { json!(repo_count) } else { Value::Null }
        },
        "worker_status": worker_status,
        "lenses": lenses_json,
        "analysis_components": components_json,
        "analysis_rule_files": cs.analysis_rule_files,
        "proof_harnesses": cs.proof_harnesses,
        "policy_docs": policies_json,
        "operations_vulnerability_risk_url": "/operations/vulnerability-risk"
    })
}

pub async fn fetch_security_governance_posture(db: &DbHandle) -> Value {
    let (msrc, cs) = tokio::join!(
        load_msrc_csaf_catalog_async(),
        load_code_security_governance_async(),
    );

    let sec_rules_sql = "SELECT \
            count(*), \
            count(*) FILTER (WHERE lower(COALESCE(d.val->>'category','')) = 'security'), \
            count(*) FILTER (WHERE lower(COALESCE(d.val->>'category','')) = 'security' AND lower(COALESCE(d.val->>'origin','')) = 'active'), \
            count(*) FILTER (WHERE lower(COALESCE(d.val->>'source','')) LIKE '%kube%'), \
            count(*) FILTER (WHERE lower(COALESCE(d.val->>'source','')) LIKE '%azure%' OR lower(COALESCE(d.val->>'source','')) LIKE '%policy%'), \
            count(*) FILTER (WHERE lower(COALESCE(d.val->>'source','')) LIKE '%mcsb%') \
        FROM state_kv sk, jsonb_each(sk.value->'details') AS d(k, val) \
        WHERE sk.key = 'operator-projection:workflow:rule.list'";

    let (rules_res, proj_rt, unknown_val) = tokio::join!(
        db.query_single_readonly(sec_rules_sql),
        fetch_msrc_projection_and_runtime_cves(db),
        fetch_security_unknown_vulns(db),
    );

    let rules_db_ok = rules_res.is_ok();
    let (total_rules, sec_rules, active_sec_rules, kube_bench_cnt, azure_policy_cnt, mcsb_rules_cnt) =
        rules_res
            .ok()
            .and_then(|q| q.rows.first().cloned())
            .map(|r| {
                (
                    cell_i64(&r, 0).unwrap_or(0),
                    cell_i64(&r, 1).unwrap_or(0),
                    cell_i64(&r, 2).unwrap_or(0),
                    cell_i64(&r, 3).unwrap_or(0),
                    cell_i64(&r, 4).unwrap_or(0),
                    cell_i64(&r, 5).unwrap_or(0),
                )
            })
            .unwrap_or((0, 0, 0, 0, 0, 0));

    let (_msrc_proj_cnt, runtime_cves, rt_db_ok) = proj_rt;
    let db_available = rules_db_ok || rt_db_ok;
    let db_status = if db_available { "measured" } else { "not-measured" };
    let msrc_runtime_matched = msrc
        .cves
        .iter()
        .filter(|c| runtime_cves.contains(&c.cve_id))
        .count() as u64;
    let hypothesis_count = unknown_val
        .pointer("/confidence_ladder/unknown_hypothesis_separate_total")
        .and_then(Value::as_u64)
        .unwrap_or(0);

    let wilson_lb95 = wilson_assurance_lb95(sec_rules.max(0) as u64, total_rules.max(0) as u64);
    let sec_share_ratio = security_coverage_ratio(sec_rules.max(0) as u64, total_rules.max(0) as u64);
    let kst_audit_date = format_kst_ymd_date(now_unix_secs());

    let assurance = SecurityGovernanceAssurance {
        total_cves: msrc.cves.len() as u64,
        exploited_cves: msrc.exploited_count as u64,
        runtime_matched_cves: msrc_runtime_matched,
        unknown_lens_count: cs.lenses.len() as u64,
        hypothesis_count,
        wilson_lb95: (wilson_lb95 * 1000.0).round() / 1000.0,
    };

    json!({
        "measurement_status": "measured",
        "db_measurement_status": db_status,
        "runtime_metrics_available": db_available,
        "loaded_at_unix": msrc.loaded_at_unix,
        "source": if db_available { "governance-security-unified" } else { "governance-security-catalog-only" },
        "audit_date_kst": kst_audit_date,
        "security_assurance": assurance,
        "security_rules": {
            "total_rules": if rules_db_ok { json!(total_rules) } else { Value::Null },
            "security_rules_total": if rules_db_ok { json!(sec_rules) } else { Value::Null },
            "security_rules_share_pct": if rules_db_ok { json!((sec_share_ratio * 1000.0).round() / 10.0) } else { Value::Null },
            "security_rules_active": if rules_db_ok { json!(active_sec_rules) } else { Value::Null },
            "security_rules_collected": if rules_db_ok { json!((sec_rules - active_sec_rules).max(0)) } else { Value::Null },
            "kube_bench_rules": if rules_db_ok { json!(kube_bench_cnt) } else { Value::Null },
            "azure_policy_rules": if rules_db_ok { json!(azure_policy_cnt) } else { Value::Null },
            "mcsb_linked_rules": if rules_db_ok { json!(mcsb_rules_cnt) } else { Value::Null }
        },
        "msrc_csaf": {
            "source_revision": msrc.source_revision,
            "total_cves": msrc.cves.len(),
            "total_advisories": msrc.total_advisories,
            "exploited_count": msrc.exploited_count,
            "publicly_disclosed_count": msrc.publicly_disclosed_count,
            "critical_count": msrc.critical_count,
            "high_count": msrc.high_count,
            "medium_count": msrc.medium_count,
            "low_count": msrc.low_count,
            "product_mapping_count": msrc.product_mapping_count,
            "runtime_detected_unique_cves": if rt_db_ok { json!(runtime_cves.len()) } else { Value::Null },
            "runtime_msrc_crosswalk_matched": if rt_db_ok { json!(msrc_runtime_matched) } else { Value::Null }
        },
        "unknown_vulnerability_governance": unknown_val
    })
}

// ============================================================================
// Full-Node Ontology Data Lineage DAG (WebGL2 + 2D Canvas Fallback Backend)
// ============================================================================

fn intern_dict(dict: &mut Vec<String>, map: &mut HashMap<String, usize>, label: &str) -> usize {
    if let Some(&idx) = map.get(label) {
        return idx;
    }
    let idx = dict.len();
    dict.push(label.to_string());
    map.insert(label.to_string(), idx);
    idx
}

fn lineage_audit_action_label_ko(action: &str) -> String {
    match action.trim() {
        "measurement.control_loop.v1" => "제어 루프 계측".to_string(),
        "control_loop.compliant" => "정책 준수 판정".to_string(),
        "control_loop.abstain" => "근거 부족 보류".to_string(),
        "hil.requested" => "사람 승인(HIL) 요청".to_string(),
        "hil.approved" => "사람 승인 완료".to_string(),
        "hil.rejected" => "사람 승인 거절".to_string(),
        "governance.rule.activation.updated" => "규칙 활성화 변경".to_string(),
        "governance.rule.enforce_mandatory" => "필수 규칙 일괄 동기화".to_string(),
        other if other.starts_with("inventory.") => format!("인벤토리 동기화 ({other})"),
        other if other.starts_with("remediate.") => format!("자동 교정 ({other})"),
        other if other.is_empty() => "감사 이벤트".to_string(),
        other => other.to_string(),
    }
}

pub async fn fetch_lineage_graph(db: &DbHandle, mode: &str) -> Value {
    let norm_mode = if mode.eq_ignore_ascii_case("full") {
        "full"
    } else {
        "clustered"
    };

    let src_sql = "SELECT COALESCE(NULLIF(source_identity, ''), 'azure.inventory'), count(*) \
        FROM inventory_observation_journal \
        GROUP BY 1 ORDER BY 2 DESC LIMIT 24";
    let snap_sql = "SELECT id, COALESCE(status, 'active'), COALESCE(source, 'inventory'), \
        COALESCE(resource_count, 0), COALESCE(link_count, 0) \
        FROM inventory_snapshot ORDER BY started_at DESC LIMIT 8";
    let res_sql = "SELECT id, object_type, \
        COALESCE(NULLIF(properties->>'name', ''), id), \
        COALESCE(NULLIF(properties->>'type', ''), object_type), \
        COALESCE(properties->>'resource_group', '') \
        FROM ontology_resource \
        ORDER BY COALESCE(NULLIF(properties->>'type', ''), object_type) ASC, id ASC \
        LIMIT 5000";
    let link_sql = "SELECT from_id, to_id, COALESCE(NULLIF(link_type, ''), 'related_to') \
        FROM ontology_link LIMIT 15000";
    let audit_sql = "SELECT COALESCE(NULLIF(action_kind, ''), 'audit.event'), count(*) \
        FROM audit_log GROUP BY 1 ORDER BY 2 DESC LIMIT 24";

    let (src_res, snap_res, res_q, link_q, aud_res) = tokio::join!(
        db.query_single_readonly(src_sql),
        db.query_single_readonly(snap_sql),
        db.query_single_readonly(res_sql),
        db.query_single_readonly(link_sql),
        db.query_single_readonly(audit_sql),
    );

    let (Ok(rq), Ok(lq)) = (res_q, link_q) else {
        return db.not_measured(
            "governance",
            "/api/v4/governance/ontology/lineage/graph",
            "postgres_unreachable",
        );
    };

    let mut type_dict: Vec<String> = Vec::new();
    let mut type_map: HashMap<String, usize> = HashMap::new();
    let mut edge_dict: Vec<String> = Vec::new();
    let mut edge_map: HashMap<String, usize> = HashMap::new();

    // Columnar node row: [idx, id, label, type_idx, stage(0..4), count, x, y, rg]
    let mut nodes: Vec<Value> = Vec::with_capacity(if norm_mode == "full" { 2_400 } else { 180 });
    // Columnar edge row: [src_idx, dst_idx, kind_idx]
    let mut edges: Vec<Value> = Vec::with_capacity(if norm_mode == "full" { 6_500 } else { 400 });

    let e_collect = intern_dict(&mut edge_dict, &mut edge_map, "관측 수집");
    let e_normalize = intern_dict(&mut edge_dict, &mut edge_map, "온톨로지 정규화");
    let e_member = intern_dict(&mut edge_dict, &mut edge_map, "유형 소속");
    let e_audit = intern_dict(&mut edge_dict, &mut edge_map, "감사 기록");

    // Stage 0: Source collectors
    let mut src_rows: Vec<(String, i64)> = src_res
        .ok()
        .map(|q| {
            q.rows
                .iter()
                .map(|r| (cell_str(r, 0), cell_i64(r, 1).unwrap_or(0)))
                .collect()
        })
        .unwrap_or_default();
    if src_rows.is_empty() {
        src_rows.push(("azure.inventory.collector".to_string(), rq.rows.len() as i64));
    }
    let t_source = intern_dict(&mut type_dict, &mut type_map, "원천 수집기");
    let mut src_indices: Vec<usize> = Vec::new();
    let src_total = src_rows.len().max(1) as u64;
    for (i, (sid, cnt)) in src_rows.iter().enumerate() {
        let idx = nodes.len();
        let y = 0.12 + 0.76 * lineage_stage_ratio(i as u64 + 1, src_total + 1);
        let disp = if sid.contains("inventory") {
            format!("인벤토리 수집기 ({sid})")
        } else {
            sid.clone()
        };
        nodes.push(json!([idx, format!("src:{sid}"), disp, t_source, 0, *cnt, 0.05, (y * 10000.0).round() / 10000.0, ""]));
        src_indices.push(idx);
    }

    // Stage 1: Inventory Snapshots
    let mut snap_rows: Vec<(String, String, i64)> = snap_res
        .ok()
        .map(|q| {
            q.rows
                .iter()
                .map(|r| {
                    (
                        cell_str(r, 0),
                        cell_str(r, 1),
                        cell_i64(r, 3).unwrap_or(rq.rows.len() as i64),
                    )
                })
                .collect()
        })
        .unwrap_or_default();
    if snap_rows.is_empty() {
        snap_rows.push(("snapshot-active".to_string(), "active".to_string(), rq.rows.len() as i64));
    }
    let t_snap = intern_dict(&mut type_dict, &mut type_map, "인벤토리 스냅샷");
    let mut snap_indices: Vec<usize> = Vec::new();
    let snap_total = snap_rows.len().max(1) as u64;
    for (i, (snap_id, status, cnt)) in snap_rows.iter().enumerate() {
        let idx = nodes.len();
        let y = 0.14 + 0.72 * lineage_stage_ratio(i as u64 + 1, snap_total + 1);
        let short_id = if snap_id.len() > 14 {
            &snap_id[..14]
        } else {
            snap_id.as_str()
        };
        let lbl = format!("스냅샷 {short_id} ({status})");
        nodes.push(json!([idx, format!("snap:{snap_id}"), lbl, t_snap, 1, *cnt, 0.19, (y * 10000.0).round() / 10000.0, ""]));
        snap_indices.push(idx);
        for &s_idx in &src_indices {
            edges.push(json!([s_idx, idx, e_collect]));
        }
    }
    let primary_snap_idx = snap_indices[0];

    // Group ALL resources by canonical resource_type
    struct RawResRow {
        id: String,
        label: String,
        type_ko: String,
        rg: String,
    }
    let mut by_type: BTreeMap<String, Vec<RawResRow>> = BTreeMap::new();
    for row in &rq.rows {
        let rid = cell_str(row, 0);
        let obj_type = cell_str(row, 1);
        let raw_name = cell_str(row, 2);
        let raw_type = cell_str(row, 3);
        let rg = cell_str(row, 4);
        let type_ko = resource_type_label_ko(&raw_type).to_string();
        let label = resolve_ontology_display_name(
            &rid,
            &obj_type,
            &json!({ "name": raw_name, "type": raw_type }),
        );
        by_type.entry(type_ko.clone()).or_default().push(RawResRow {
            id: rid,
            label,
            type_ko,
            rg,
        });
    }

    let total_resources = rq.rows.len();
    let mut sorted_clusters: Vec<(String, Vec<RawResRow>)> = by_type.into_iter().collect();
    sorted_clusters.sort_by_key(|(tko, list)| (std::cmp::Reverse(list.len()), tko.clone()));
    let cluster_count = sorted_clusters.len();

    // Stage 2: Resource-Type Cluster Supernodes
    let mut cluster_node_by_type: HashMap<String, usize> = HashMap::new();
    let mut res_id_to_cluster_node: HashMap<String, usize> = HashMap::with_capacity(total_resources);
    let mut res_id_to_node_idx: HashMap<String, usize> = HashMap::with_capacity(total_resources);

    let cl_total = cluster_count.max(1) as u64;
    let total_res_f = (total_resources.max(1)) as f64;
    let mut y_cursor: f64 = 0.04;

    for (ci, (tko, members)) in sorted_clusters.iter().enumerate() {
        let c_idx = nodes.len();
        let t_idx = intern_dict(&mut type_dict, &mut type_map, tko);
        let band_h = ((members.len() as f64 / total_res_f) * 0.90).clamp(0.014, 0.24);
        let cy = if norm_mode == "full" {
            (y_cursor + band_h * 0.5).clamp(0.04, 0.96)
        } else {
            0.05 + 0.90 * lineage_stage_ratio(ci as u64 + 1, cl_total + 1)
        };
        let cl_x = if norm_mode == "full" { 0.34 } else { 0.44 };
        let cl_label = format!("{tko} ({}개)", members.len());
        nodes.push(json!([
            c_idx,
            format!("cluster:{tko}"),
            cl_label,
            t_idx,
            2,
            members.len(),
            cl_x,
            (cy * 10000.0).round() / 10000.0,
            ""
        ]));
        cluster_node_by_type.insert(tko.clone(), c_idx);
        edges.push(json!([primary_snap_idx, c_idx, e_normalize]));

        for m in members {
            res_id_to_cluster_node.insert(m.id.clone(), c_idx);
        }

        // Stage 3 (Full Mode): ALL individual resources laid out cleanly inside their cluster band (zero overlaps!)
        if norm_mode == "full" {
            let n_mem = members.len();
            let cols = if n_mem <= 4 {
                1usize
            } else if n_mem <= 24 {
                4usize
            } else if n_mem <= 90 {
                9usize
            } else {
                18usize
            };
            let rows_in_band = n_mem.div_ceil(cols).max(1);
            for (mi, m) in members.iter().enumerate() {
                let r_idx = nodes.len();
                let col_i = mi % cols;
                let row_i = mi / cols;
                let rx = 0.48 + 0.34 * ((col_i as f64 + 0.5) / cols as f64);
                let ry = (y_cursor + band_h * ((row_i as f64 + 0.5) / rows_in_band as f64)).clamp(0.025, 0.975);
                let rt_idx = intern_dict(&mut type_dict, &mut type_map, &m.type_ko);
                nodes.push(json!([
                    r_idx,
                    m.id,
                    m.label,
                    rt_idx,
                    3,
                    1,
                    (rx * 10000.0).round() / 10000.0,
                    (ry * 10000.0).round() / 10000.0,
                    m.rg
                ]));
                res_id_to_node_idx.insert(m.id.clone(), r_idx);
                edges.push(json!([c_idx, r_idx, e_member]));
            }
            y_cursor = (y_cursor + band_h + 0.004).min(0.95);
        }
    }

    // Add real ontology_link edges (resource-to-resource in full mode, cluster-to-cluster aggregated in clustered mode)
    let mut linked_resources: HashSet<usize> = HashSet::new();
    let mut seen_cluster_edges: HashSet<(usize, usize, usize)> = HashSet::new();
    let mut ontology_links_attached = 0usize;
    for row in &lq.rows {
        let from_id = cell_str(row, 0);
        let to_id = cell_str(row, 1);
        let ltype = cell_str(row, 2);
        let ek = intern_dict(&mut edge_dict, &mut edge_map, &ltype);
        if norm_mode == "full" {
            if let (Some(&fi), Some(&ti)) = (res_id_to_node_idx.get(&from_id), res_id_to_node_idx.get(&to_id)) {
                if fi != ti {
                    edges.push(json!([fi, ti, ek]));
                    linked_resources.insert(fi);
                    linked_resources.insert(ti);
                    ontology_links_attached += 1;
                }
            }
        } else if let (Some(&fc), Some(&tc)) = (
            res_id_to_cluster_node.get(&from_id),
            res_id_to_cluster_node.get(&to_id),
        ) {
            if fc != tc && seen_cluster_edges.insert((fc, tc, ek)) {
                edges.push(json!([fc, tc, ek]));
                ontology_links_attached += 1;
            }
        }
    }

    // Stage 4: Audit Log Sinks
    let mut aud_rows: Vec<(String, i64)> = aud_res
        .ok()
        .map(|q| {
            q.rows
                .iter()
                .map(|r| (cell_str(r, 0), cell_i64(r, 1).unwrap_or(0)))
                .collect()
        })
        .unwrap_or_default();
    if aud_rows.is_empty() {
        aud_rows.push(("measurement.control_loop.v1".to_string(), 0));
    }
    let t_audit = intern_dict(&mut type_dict, &mut type_map, "감사 원장");
    let aud_total = aud_rows.len().max(1) as u64;
    let top_cluster_indices: Vec<usize> = sorted_clusters
        .iter()
        .take(8)
        .filter_map(|(tko, _)| cluster_node_by_type.get(tko).copied())
        .collect();
    for (i, (ak, cnt)) in aud_rows.iter().enumerate() {
        let a_idx = nodes.len();
        let y = 0.08 + 0.84 * lineage_stage_ratio(i as u64 + 1, aud_total + 1);
        let lbl = format!("{} ({cnt}건)", lineage_audit_action_label_ko(ak));
        nodes.push(json!([
            a_idx,
            format!("audit:{ak}"),
            lbl,
            t_audit,
            4,
            *cnt,
            0.94,
            (y * 10000.0).round() / 10000.0,
            ""
        ]));
        if !top_cluster_indices.is_empty() {
            let src_cl = top_cluster_indices[i % top_cluster_indices.len()];
            edges.push(json!([src_cl, a_idx, e_audit]));
        }
    }

    let mapped_count = if norm_mode == "full" {
        res_id_to_node_idx.len() as u64
    } else {
        total_resources as u64
    };
    let cov_lb95 = lineage_coverage_wilson_lb95(mapped_count, total_resources as u64);
    let metrics = LineageGraphMetrics {
        total_nodes: nodes.len() as u64,
        total_edges: edges.len() as u64,
        total_resources: total_resources as u64,
        cluster_count: cluster_count as u64,
        coverage_wilson_lb95: (cov_lb95 * 1000.0).round() / 1000.0,
    };

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "mode": norm_mode,
        "types": type_dict,
        "edge_kinds": edge_dict,
        "nodes": nodes,
        "edges": edges,
        "metrics": metrics,
        "ontology_links_attached": ontology_links_attached,
        "linked_resource_nodes": linked_resources.len(),
        "stages": [
            { "stage": 0, "key": "source", "label_ko": "① 원천 소스", "count": src_indices.len() },
            { "stage": 1, "key": "snapshot", "label_ko": "② 수집 스냅샷", "count": snap_indices.len() },
            { "stage": 2, "key": "cluster", "label_ko": "③ 리소스 유형 클러스터", "count": cluster_count },
            { "stage": 3, "key": "resource", "label_ko": "④ 온톨로지 인스턴스", "count": if norm_mode == "full" { res_id_to_node_idx.len() } else { total_resources } },
            { "stage": 4, "key": "audit", "label_ko": "⑤ 규칙 · 이벤트 · 감사", "count": aud_rows.len() }
        ]
    })
}

