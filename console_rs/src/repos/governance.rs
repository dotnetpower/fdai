//! Domain 4 (`governance`, 13 panels) PostgreSQL repository, including Foundry+ Data Lineage.
//!
//! Queries live local/managed PostgreSQL projections and tables directly with bounded
//! read-only queries (`DbHandle::query_single_readonly`) and audited KV mutations
//! (`DbHandle::execute_audited_kv_mutation`). Never fabricates `0` when unreachable.

use crate::db::{cell_i64, cell_str, clamp_limit, quote_like_contains, DbHandle};
use fdai_adapter_postgres::pg_quote_literal;
use serde_json::{json, Map, Value};
use std::collections::HashMap;

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
pub fn resolve_ontology_display_name(id: &str, object_type: &str, props: &Value) -> String {
    let pick = |key: &str| -> Option<String> {
        props
            .get(key)
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(String::from)
    };
    if let Some(name) = pick("name") {
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
    if let Some(ptype) = pick("provider_type") {
        return format!("{id} ({ptype})");
    }
    if let Some(sem) = pick("semantic_id") {
        let short_id = id.strip_prefix("property.").unwrap_or(id);
        return format!("{short_id} ({sem})");
    }
    if let Some(rest) = id.strip_prefix("review-") {
        let short: String = rest.chars().take(8).collect();
        let st = pick("status").unwrap_or_else(|| "open".to_string());
        return format!("검토 케이스 #{short} ({st})");
    }
    if let Some(rest) = id.strip_prefix("check-") {
        let short: String = rest.chars().take(8).collect();
        let st = pick("status").unwrap_or_else(|| "open".to_string());
        return format!("검토 점검 #{short} ({st})");
    }
    if let Some(rest) = id.strip_prefix("benchmark-validation:") {
        let short: String = rest.chars().take(8).collect();
        return format!("벤치마크 검증 #{short}");
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
            return last.to_string();
        }
    }
    if clean.is_empty() {
        ontology_type_label_ko(object_type).to_string()
    } else {
        clean.to_string()
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
                    let props: Value =
                        serde_json::from_str(&cell_str(row, 6)).unwrap_or_else(|_| json!({}));
                    let dname = resolve_ontology_display_name(&nid, &ot, &props);
                    json!({
                        "id": nid,
                        "hop": cell_i64(row, 1),
                        "object_type": ot,
                        "object_type_ko": ontology_type_label_ko(&ot),
                        "name": dname,
                        "display_name": dname,
                        "resource_type": cell_str(row, 4),
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
    let lim = clamp_limit(limit, 100, 200);
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
            "activation_policy": if mandatory_active { "mandatory_critical_high" } else { "operator_configurable" }
        }));
    }

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "mandatory_severities": ["critical", "high"],
        "total": total_all,
        "filtered_total": filtered_total,
        "limit": lim,
        "offset": off,
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
        "rules": rules,
        "items": rules
    })
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
                      COALESCE(entry->>'reason', entry->>'t1_reason', entry->>'stage', action_kind) \
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
                    COALESCE(NULLIF(entry->>'reason', ''), NULLIF(entry->>'outcome', ''), NULLIF(entry->>'mode', ''), '') \
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
        let search_clause = match clean_opt(search) {
            Some(q) => {
                let pat = quote_like_contains(q);
                format!(
                    " AND (COALESCE(d.val->>'id','') ILIKE {pat} ESCAPE '\\' \
                     OR COALESCE(d.val->'explanation'->'details'->>'title_ko','') ILIKE {pat} ESCAPE '\\')"
                )
            }
            None => String::new(),
        };
        let msrc_list_sql = format!(
            "SELECT \
                COALESCE(d.val->>'id', ''), \
                COALESCE(d.val->>'id', ''), \
                COALESCE(d.val->'explanation'->'details'->>'title_ko', d.val->'explanation'->>'title', d.val->>'id', ''), \
                COALESCE(d.val->>'category', 'security'), \
                COALESCE(d.val->>'severity', 'high'), \
                COALESCE(d.val->'explanation'->'details'->>'description_ko', ''), \
                COALESCE(d.val->'provenance'->>'source_url', ''), \
                'security-owner', \
                COALESCE(d.val->>'origin', 'collected'), \
                '{{}}', \
                '[]', \
                '[]' \
             FROM state_kv sk, jsonb_each(sk.value->'details') AS d(k, val) \
             WHERE sk.key = 'operator-projection:workflow:rule.list' \
               AND lower(COALESCE(d.val->>'source','')) IN ('msrc', 'msrc_csaf', 'csaf', 'security_advisory') \
               {search_clause} \
             LIMIT {lim} OFFSET {off}"
        );
        let (a, b, c) = tokio::join!(
            db.query_single_readonly(counts_sql),
            db.query_single_readonly(msrc_cnt_sql),
            db.query_single_readonly(&msrc_list_sql),
        );
        (a, b, Some(c))
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

    let (msrc_cnt, security_rule_cnt) = msrc_res
        .ok()
        .and_then(|r| r.rows.first().cloned())
        .map(|row| {
            (
                cell_i64(&row, 0).unwrap_or(0),
                cell_i64(&row, 1).unwrap_or(0),
            )
        })
        .unwrap_or((0, 0));

    let mut controls: Vec<Value> = Vec::new();
    if let Some(Ok(lq)) = controls_res {
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
