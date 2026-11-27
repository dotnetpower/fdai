//! Domain 2 (`operations`, 18 panels) PostgreSQL repository.
//! Bounded read-only queries against local/runtime PostgreSQL with honest `not-measured` envelopes.

use crate::db::{cell_i64, cell_str, clamp_limit, quote_like_contains, DbHandle};
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;

fn parse_json_cell(row: &[Option<String>], idx: usize) -> Value {
    let raw = cell_str(row, idx);
    if raw.is_empty() {
        Value::Null
    } else {
        serde_json::from_str::<Value>(&raw).unwrap_or(Value::Null)
    }
}

fn str_field(val: &Value, path: &[&str]) -> String {
    let mut cur = val;
    for key in path {
        let Some(next) = cur.get(*key) else {
            return String::new();
        };
        cur = next;
    }
    match cur {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        Value::Bool(b) => b.to_string(),
        _ => String::new(),
    }
}

fn num_field(val: &Value, path: &[&str]) -> Option<f64> {
    let mut cur = val;
    for key in path {
        cur = cur.get(*key)?;
    }
    cur.as_f64()
        .or_else(|| cur.as_i64().map(|v| v as f64))
        .or_else(|| cur.as_str().and_then(|s| s.parse::<f64>().ok()))
}

pub async fn fetch_summary(db: &DbHandle) -> Value {
    let inc_sql = "SELECT count(*), \
                   SUM(CASE WHEN projected_state NOT IN ('resolved', 'closed') THEN 1 ELSE 0 END) \
                   FROM operator_incident_projection";
    let hil_sql = "SELECT count(*) FROM state_kv WHERE key LIKE 'hil_park:%'";
    let find_sql = "SELECT count(*) FROM state_kv WHERE key LIKE 'runtime:analyzer-finding-current:%'";
    let cov_sql = "SELECT count(*), SUM(CASE WHEN complete THEN 1 ELSE 0 END) \
                   FROM operational_state_transition_coverage";
    let snap_sql = "SELECT id, status, COALESCE(resource_count, 0), COALESCE(link_count, 0), \
                    COALESCE(to_char(completed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') \
                    FROM inventory_snapshot WHERE status = 'active' ORDER BY started_at DESC LIMIT 1";
    let cs_sql = "SELECT value::text FROM state_kv \
                  WHERE key LIKE 'runtime:code-security-issues:%' AND key NOT LIKE '%:artifacts%' \
                  ORDER BY updated_at DESC LIMIT 10";
    let scope_sql = "SELECT value::text FROM state_kv WHERE key = 'operator-projection:operations:scope.effective' LIMIT 1";
    let (Ok(inc), Ok(hil), Ok(find), Ok(cov), Ok(snap), cs_res, scope_res) = tokio::join!(
        db.query_single_readonly(inc_sql),
        db.query_single_readonly(hil_sql),
        db.query_single_readonly(find_sql),
        db.query_single_readonly(cov_sql),
        db.query_single_readonly(snap_sql),
        db.query_single_readonly(cs_sql),
        db.query_single_readonly(scope_sql),
    ) else {
        return db.not_measured("operations", "/api/v4/operations/summary", "postgres_unreachable");
    };

    let inc_total = inc.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let inc_open = inc.rows.first().and_then(|r| cell_i64(r, 1)).unwrap_or(0);
    let hil_total = hil.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let active_findings = find.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let cov_total = cov.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let cov_complete = cov.rows.first().and_then(|r| cell_i64(r, 1)).unwrap_or(0);
    let mut cs_total: i64 = 0;
    let mut cs_crit_high: i64 = 0;
    if let Ok(cs) = cs_res {
        for row in &cs.rows {
            let parsed = parse_json_cell(row, 0);
            if let Some(arr) = parsed.get("issues").and_then(Value::as_array) {
                for item in arr {
                    cs_total += 1;
                    let sev = str_field(item, &["severity"]).to_ascii_lowercase();
                    if sev == "critical" || sev == "high" {
                        cs_crit_high += 1;
                    }
                }
            }
        }
    }
    let effective_scope = scope_res
        .ok()
        .and_then(|r| r.rows.first().map(|row| parse_json_cell(row, 0)))
        .unwrap_or(Value::Null);
    let active_snap = snap.rows.first().map(|r| {
        json!({
            "snapshot_id": cell_str(r, 0),
            "status": cell_str(r, 1),
            "resource_count": cell_i64(r, 2).unwrap_or(0),
            "link_count": cell_i64(r, 3).unwrap_or(0),
            "completed_at": cell_str(r, 4)
        })
    });

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "incidents": {
            "total": inc_total,
            "open": inc_open
        },
        "hil_queue": {
            "pending_total": hil_total
        },
        "code_security": {
            "total": cs_total,
            "critical_high": cs_crit_high
        },
        "findings": {
            "active_count": active_findings
        },
        "detection_readiness": {
            "coverage_records": cov_total,
            "complete_records": cov_complete
        },
        "effective_scope": effective_scope,
        "active_snapshot": active_snap
    })
}

pub async fn fetch_live_inventory(db: &DbHandle) -> Value {
    let rt_sql = "SELECT resource_id, change_kind, resource_type, COALESCE(provider_ref, ''), \
                  to_char(observed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                  FROM inventory_realtime_resource ORDER BY observed_at DESC LIMIT 40";
    let dlv_sql = "SELECT delivery_id, channel_kind, state, attempt_count, \
                   to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                   FROM conversation_outbound_delivery ORDER BY created_at DESC LIMIT 30";
    let inc_sql = "SELECT correlation_id, projected_state, projected_vertical, projected_severity, \
                   COALESCE(canonical_incident_number, canonical_incident_id, correlation_id), \
                   COALESCE(canonical_opened_at, '') \
                   FROM operator_incident_projection ORDER BY last_seq DESC LIMIT 12";
    let hil_cnt_sql = "SELECT count(*) FROM state_kv WHERE key LIKE 'hil_park:%'";
    let hil_top_sql = "SELECT key, value::text, \
                       to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                       FROM state_kv WHERE key LIKE 'hil_park:%' ORDER BY updated_at DESC LIMIT 8";
    let src_sql = "SELECT key, value::text, \
                   to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                   FROM state_kv WHERE key LIKE 'observation-campaign:source:%' ORDER BY key LIMIT 16";
    let snap_sql = "SELECT id, status, source, COALESCE(resource_count, 0), COALESCE(link_count, 0), \
                    COALESCE(to_char(completed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') \
                    FROM inventory_snapshot ORDER BY started_at DESC LIMIT 3";
    let trans_sql = "SELECT transition_id, subject_ref, subject_type, state_type, \
                     COALESCE(from_state, ''), to_state, lane, source_identity, \
                     to_char(recorded_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                     FROM operational_state_transition ORDER BY recorded_at DESC LIMIT 16";
    let hm_sql = "WITH unified_ops AS ( \
                    SELECT created_at AS ts, mode, action_kind FROM (SELECT created_at, mode, action_kind FROM audit_log ORDER BY seq DESC LIMIT 4000) a \
                    UNION ALL \
                    SELECT observed_at AS ts, 'observed' AS mode, 'inventory.' || change_kind AS action_kind FROM (SELECT observed_at, change_kind FROM inventory_realtime_resource ORDER BY observed_at DESC LIMIT 1000) r \
                    UNION ALL \
                    SELECT recorded_at AS ts, lane AS mode, 'transition.' || state_type AS action_kind FROM (SELECT recorded_at, lane, state_type FROM operational_state_transition ORDER BY recorded_at DESC LIMIT 2000) t \
                    UNION ALL \
                    SELECT created_at AS ts, state AS mode, 'delivery.' || channel_kind AS action_kind FROM (SELECT created_at, state, channel_kind FROM conversation_outbound_delivery ORDER BY created_at DESC LIMIT 500) d \
                  ) \
                  SELECT EXTRACT(ISODOW FROM ts AT TIME ZONE 'UTC')::int AS dow, \
                         EXTRACT(HOUR FROM ts AT TIME ZONE 'UTC')::int AS utc_hour, \
                         to_char(date_trunc('hour', ts AT TIME ZONE 'UTC'), 'YYYY-MM-DD\"T\"HH24:') || \
                         CASE WHEN EXTRACT(MINUTE FROM ts AT TIME ZONE 'UTC') >= 30 THEN '30:00Z' ELSE '00:00Z' END AS slot_utc, \
                         count(*)::bigint AS total, \
                         SUM(CASE WHEN mode = 'shadow' THEN 1 ELSE 0 END)::bigint AS shadow_cnt, \
                         SUM(CASE WHEN action_kind LIKE '%hil%' OR action_kind LIKE '%approval%' THEN 1 ELSE 0 END)::bigint AS hil_cnt, \
                         SUM(CASE WHEN action_kind LIKE '%deny%' OR action_kind LIKE '%block%' THEN 1 ELSE 0 END)::bigint AS deny_cnt \
                  FROM unified_ops \
                  WHERE ts IS NOT NULL \
                  GROUP BY 1, 2, 3 ORDER BY 3 DESC, 1, 2";
    let hm_day_sql = "WITH unified_ops AS ( \
                        SELECT created_at AS ts, mode, action_kind FROM (SELECT created_at, mode, action_kind FROM audit_log ORDER BY seq DESC LIMIT 4000) a \
                        UNION ALL \
                        SELECT observed_at AS ts, 'observed' AS mode, 'inventory.' || change_kind AS action_kind FROM (SELECT observed_at, change_kind FROM inventory_realtime_resource ORDER BY observed_at DESC LIMIT 1000) r \
                        UNION ALL \
                        SELECT recorded_at AS ts, lane AS mode, 'transition.' || state_type AS action_kind FROM (SELECT recorded_at, lane, state_type FROM operational_state_transition ORDER BY recorded_at DESC LIMIT 2000) t \
                        UNION ALL \
                        SELECT created_at AS ts, state AS mode, 'delivery.' || channel_kind AS action_kind FROM (SELECT created_at, state, channel_kind FROM conversation_outbound_delivery ORDER BY created_at DESC LIMIT 500) d \
                      ), anchor AS (SELECT MAX(ts) AS max_ts FROM unified_ops) \
                      SELECT to_char(date_trunc('hour', u.ts AT TIME ZONE 'UTC'), 'YYYY-MM-DD\"T\"HH24:') || \
                             LPAD((FLOOR(EXTRACT(MINUTE FROM u.ts AT TIME ZONE 'UTC') / 5)::int * 5)::text, 2, '0') || ':00Z' AS slot_utc, \
                             count(*)::bigint AS total, \
                             SUM(CASE WHEN u.mode = 'shadow' THEN 1 ELSE 0 END)::bigint AS shadow_cnt, \
                             SUM(CASE WHEN u.action_kind LIKE '%hil%' OR u.action_kind LIKE '%approval%' THEN 1 ELSE 0 END)::bigint AS hil_cnt, \
                             SUM(CASE WHEN u.action_kind LIKE '%deny%' OR u.action_kind LIKE '%block%' THEN 1 ELSE 0 END)::bigint AS deny_cnt \
                      FROM unified_ops u, anchor \
                      WHERE anchor.max_ts IS NOT NULL \
                        AND u.ts >= anchor.max_ts - INTERVAL '24 hours' \
                      GROUP BY 1 ORDER BY 1";
    let scope_sql = "SELECT value::text FROM state_kv WHERE key = 'operator-projection:operations:scope.effective' LIMIT 1";
    let onto_sql = "SELECT count(*) FROM ontology_resource";

    let (
        Ok(rt),
        Ok(dlv),
        Ok(inc),
        Ok(hil_cnt),
        Ok(hil_top),
        Ok(src),
        Ok(snap),
        Ok(trans),
        Ok(hm),
        hm_day_res,
        scope_res,
        onto_res,
    ) = tokio::join!(
        db.query_single_readonly(rt_sql),
        db.query_single_readonly(dlv_sql),
        db.query_single_readonly(inc_sql),
        db.query_single_readonly(hil_cnt_sql),
        db.query_single_readonly(hil_top_sql),
        db.query_single_readonly(src_sql),
        db.query_single_readonly(snap_sql),
        db.query_single_readonly(trans_sql),
        db.query_single_readonly(hm_sql),
        db.query_single_readonly(hm_day_sql),
        db.query_single_readonly(scope_sql),
        db.query_single_readonly(onto_sql),
    ) else {
        return db.not_measured("operations", "/api/v4/operations/live", "postgres_unreachable");
    };

    let effective_scope = scope_res
        .ok()
        .and_then(|r| r.rows.first().map(|row| parse_json_cell(row, 0)))
        .unwrap_or(Value::Null);
    let ontology_resource_count = onto_res
        .ok()
        .and_then(|r| r.rows.first().and_then(|row| cell_i64(row, 0)))
        .unwrap_or(0);

    let hil_total = hil_cnt
        .rows
        .first()
        .and_then(|r| cell_i64(r, 0))
        .unwrap_or(0);

    let active_snapshot = snap.rows.first().map(|r| {
        json!({
            "snapshot_id": cell_str(r, 0),
            "status": cell_str(r, 1),
            "source": cell_str(r, 2),
            "resource_count": cell_i64(r, 3).unwrap_or(0),
            "link_count": cell_i64(r, 4).unwrap_or(0),
            "completed_at": cell_str(r, 5)
        })
    });

    let source_health: Vec<Value> = src
        .rows
        .iter()
        .map(|r| {
            let v = parse_json_cell(r, 1);
            json!({
                "key": cell_str(r, 0),
                "source_id": str_field(&v, &["source_id"]),
                "domain": str_field(&v, &["domain"]),
                "status": str_field(&v, &["status"]),
                "coverage": str_field(&v, &["coverage"]),
                "freshness": str_field(&v, &["freshness"]),
                "owner_agent": str_field(&v, &["owner_agent"]),
                "duration_ms": num_field(&v, &["duration_ms"]),
                "reason_codes": v.get("reason_codes").cloned().unwrap_or_else(|| json!([])),
                "updated_at": cell_str(r, 2)
            })
        })
        .collect();

    let hil_preview: Vec<Value> = hil_top
        .rows
        .iter()
        .map(|r| {
            let v = parse_json_cell(r, 1);
            json!({
                "approval_id": str_field(&v, &["approval_id"]),
                "rule_id": str_field(&v, &["rule_id"]),
                "action_type": str_field(&v, &["action_type"]),
                "severity": str_field(&v, &["severity"]),
                "status": str_field(&v, &["status"]),
                "target": str_field(&v, &["action", "target_resource_ref"]),
                "updated_at": cell_str(r, 2)
            })
        })
        .collect();

    let heatmap_total_events: i64 = hm
        .rows
        .iter()
        .map(|r| cell_i64(r, 3).unwrap_or(0))
        .sum();
    let heatmap_buckets: Vec<Value> = hm
        .rows
        .iter()
        .map(|r| {
            let utc_hour = cell_i64(r, 1).unwrap_or(0).clamp(0, 23);
            json!({
                "dow": cell_i64(r, 0).unwrap_or(1),
                "hour": utc_hour,
                "bucket": utc_hour / 2,
                "slot_utc": cell_str(r, 2),
                "total": cell_i64(r, 3).unwrap_or(0),
                "shadow": cell_i64(r, 4).unwrap_or(0),
                "hil": cell_i64(r, 5).unwrap_or(0),
                "deny": cell_i64(r, 6).unwrap_or(0)
            })
        })
        .collect();
    let mut heatmap_day_total_events: i64 = 0;
    let mut heatmap_day_buckets: Vec<Value> = Vec::new();
    let mut heatmap_anchor_at = String::new();
    if let Ok(hm_day) = hm_day_res {
        for r in &hm_day.rows {
            let slot_utc = cell_str(r, 0);
            let tot = cell_i64(r, 1).unwrap_or(0);
            heatmap_day_total_events += tot;
            if !slot_utc.is_empty() {
                heatmap_anchor_at = slot_utc.clone();
            }
            heatmap_day_buckets.push(json!({
                "slot_utc": slot_utc,
                "total": tot,
                "shadow": cell_i64(r, 2).unwrap_or(0),
                "hil": cell_i64(r, 3).unwrap_or(0),
                "deny": cell_i64(r, 4).unwrap_or(0)
            }));
        }
    }
    if heatmap_anchor_at.is_empty() {
        heatmap_anchor_at = hm
            .rows
            .first()
            .map(|r| cell_str(r, 2))
            .unwrap_or_default();
    }

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "active_snapshot": active_snapshot,
        "effective_scope": effective_scope,
        "ontology_resource_count": ontology_resource_count,
        "hil_pending_count": hil_total,
        "realtime_resources": rt.rows.iter().map(|r| json!({
            "resource_id": cell_str(r, 0),
            "change_kind": cell_str(r, 1),
            "resource_type": cell_str(r, 2),
            "provider_ref": cell_str(r, 3),
            "observed_at": cell_str(r, 4)
        })).collect::<Vec<_>>(),
        "incidents": inc.rows.iter().map(|r| json!({
            "correlation_id": cell_str(r, 0),
            "state": cell_str(r, 1),
            "vertical": cell_str(r, 2),
            "severity": cell_str(r, 3),
            "incident_number": cell_str(r, 4),
            "opened_at": cell_str(r, 5)
        })).collect::<Vec<_>>(),
        "hil_preview": hil_preview,
        "source_health": source_health,
        "state_transitions": trans.rows.iter().map(|r| json!({
            "transition_id": cell_str(r, 0),
            "subject_ref": cell_str(r, 1),
            "subject_type": cell_str(r, 2),
            "state_type": cell_str(r, 3),
            "from_state": cell_str(r, 4),
            "to_state": cell_str(r, 5),
            "lane": cell_str(r, 6),
            "source_identity": cell_str(r, 7),
            "recorded_at": cell_str(r, 8)
        })).collect::<Vec<_>>(),
        "heatmap_buckets": heatmap_buckets,
        "heatmap_day_buckets": heatmap_day_buckets,
        "heatmap_anchor_at": heatmap_anchor_at,
        "heatmap_timezone": "UTC",
        "heatmap_total_events": heatmap_total_events,
        "heatmap_day_total_events": heatmap_day_total_events,
        "outbound_deliveries": dlv.rows.iter().map(|r| json!({
            "delivery_id": cell_str(r, 0),
            "channel_kind": cell_str(r, 1),
            "state": cell_str(r, 2),
            "attempt_count": cell_i64(r, 3),
            "created_at": cell_str(r, 4)
        })).collect::<Vec<_>>()
    })
}

pub async fn fetch_live_stream_snapshot(db: &DbHandle) -> Value {
    let started = std::time::Instant::now();
    let rt_sql = "SELECT resource_id, change_kind, resource_type, \
                  to_char(observed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                  FROM inventory_realtime_resource ORDER BY observed_at DESC LIMIT 10";
    let inc_sql = "SELECT correlation_id, projected_state, projected_vertical, projected_severity, \
                   COALESCE(canonical_incident_number, canonical_incident_id, correlation_id) \
                   FROM operator_incident_projection ORDER BY last_seq DESC LIMIT 10";
    let hil_cnt_sql = "SELECT count(*) FROM state_kv WHERE key LIKE 'hil_park:%'";
    let hil_sql = "SELECT key, value::text, \
                   to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                   FROM state_kv WHERE key LIKE 'hil_park:%' ORDER BY updated_at DESC LIMIT 40";
    let snap_sql = "SELECT COALESCE(resource_count, 0), COALESCE(link_count, 0), status \
                    FROM inventory_snapshot WHERE status = 'active' ORDER BY started_at DESC LIMIT 1";
    let audit_sql = "SELECT seq, COALESCE(correlation_id, ''), action_kind, COALESCE(actor, ''), \
                     COALESCE(mode, ''), \
                     to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
                     COALESCE(entry->'payload'->>'resource_id', entry->>'resource_id', entry->>'target_resource_ref', entry->>'resource_type', ''), \
                     COALESCE(entry->>'rule_id', ''), \
                     COALESCE(entry->>'action_type', ''), \
                     COALESCE(entry->>'severity', ''), \
                     COALESCE(entry->>'approval_id', ''), \
                     COALESCE(entry->>'reason', entry->>'rca_cause', '') \
                     FROM audit_log ORDER BY seq DESC LIMIT 8";

    let (Ok(rt), Ok(inc), Ok(hil_cnt), Ok(hil), Ok(snap), audit_res) = tokio::join!(
        db.query_single_readonly(rt_sql),
        db.query_single_readonly(inc_sql),
        db.query_single_readonly(hil_cnt_sql),
        db.query_single_readonly(hil_sql),
        db.query_single_readonly(snap_sql),
        db.query_single_readonly(audit_sql),
    ) else {
        return db.not_measured(
            "operations",
            "/api/v4/operations/live/stream",
            "postgres_unreachable",
        );
    };

    let db_latency_ms = u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX);
    let hil_total = hil_cnt
        .rows
        .first()
        .and_then(|r| cell_i64(r, 0))
        .unwrap_or(0);
    let resource_count = snap.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0);
    let link_count = snap.rows.first().and_then(|r| cell_i64(r, 1)).unwrap_or(0);

    let mut hil_by_corr: BTreeMap<String, Value> = BTreeMap::new();
    let mut hil_by_approval: BTreeMap<String, Value> = BTreeMap::new();
    let mut hil_queue_items: Vec<Value> = Vec::new();
    for (idx, r) in hil.rows.iter().enumerate() {
        let v = parse_json_cell(r, 1);
        let approval_id = str_field(&v, &["approval_id"]);
        let corr_id = str_field(&v, &["correlation_id"]);
        let item = json!({
            "key": cell_str(r, 0),
            "approval_id": approval_id,
            "correlation_id": corr_id,
            "rule_id": str_field(&v, &["rule_id"]),
            "action_type": str_field(&v, &["action_type"]),
            "severity": str_field(&v, &["severity"]),
            "status": str_field(&v, &["status"]),
            "target": str_field(&v, &["action", "target_resource_ref"]),
            "updated_at": cell_str(r, 2)
        });
        if !corr_id.is_empty() {
            hil_by_corr.entry(corr_id).or_insert_with(|| item.clone());
        }
        if !approval_id.is_empty() {
            hil_by_approval
                .entry(approval_id)
                .or_insert_with(|| item.clone());
        }
        if idx < 5 {
            hil_queue_items.push(item);
        }
    }

    let mut latest_audit_seq: Option<i64> = None;
    let mut latest_audit_events: Vec<Value> = Vec::new();
    if let Ok(aud) = audit_res {
        latest_audit_seq = aud.rows.first().and_then(|r| cell_i64(r, 0));
        for r in &aud.rows {
            let corr_id = cell_str(r, 1);
            let mut target = cell_str(r, 6);
            let mut rule_id = cell_str(r, 7);
            let mut action_type = cell_str(r, 8);
            let mut severity = cell_str(r, 9);
            let mut approval_id = cell_str(r, 10);
            let reason = cell_str(r, 11);

            let linked_hil = hil_by_approval
                .get(&approval_id)
                .or_else(|| hil_by_corr.get(&corr_id));
            if let Some(h) = linked_hil {
                if target.is_empty() {
                    target = str_field(h, &["target"]);
                }
                if rule_id.is_empty() {
                    rule_id = str_field(h, &["rule_id"]);
                }
                if action_type.is_empty() {
                    action_type = str_field(h, &["action_type"]);
                }
                if severity.is_empty() {
                    severity = str_field(h, &["severity"]);
                }
                if approval_id.is_empty() {
                    approval_id = str_field(h, &["approval_id"]);
                }
            }
            let resource_name = target
                .rsplit('/')
                .next()
                .filter(|s| !s.is_empty())
                .unwrap_or("")
                .to_string();
            latest_audit_events.push(json!({
                "seq": cell_i64(r, 0),
                "correlation_id": corr_id,
                "action_kind": cell_str(r, 2),
                "actor": cell_str(r, 3),
                "mode": cell_str(r, 4),
                "created_at": cell_str(r, 5),
                "target": target,
                "resource_name": resource_name,
                "rule_id": rule_id,
                "action_type": action_type,
                "severity": severity,
                "approval_id": approval_id,
                "reason": reason
            }));
        }
    }
    let observed_at = latest_audit_events
        .first()
        .and_then(|e| e.get("created_at").and_then(Value::as_str))
        .filter(|s| !s.is_empty())
        .map(ToString::to_string)
        .or_else(|| {
            rt.rows
                .first()
                .map(|r| cell_str(r, 3))
                .filter(|s| !s.is_empty())
        })
        .unwrap_or_default();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "db_latency_ms": db_latency_ms,
        "observed_at": observed_at,
        "latest_audit_seq": latest_audit_seq,
        "latest_audit_events": latest_audit_events,
        "counts": {
            "realtime_resources": rt.rows.len(),
            "incidents": inc.rows.len(),
            "hil_pending": hil_total,
            "observed_resources": resource_count,
            "observed_links": link_count
        },
        "realtime_resources": rt.rows.iter().map(|r| json!({
            "resource_id": cell_str(r, 0),
            "change_kind": cell_str(r, 1),
            "resource_type": cell_str(r, 2),
            "observed_at": cell_str(r, 3)
        })).collect::<Vec<_>>(),
        "incidents": inc.rows.iter().map(|r| json!({
            "correlation_id": cell_str(r, 0),
            "state": cell_str(r, 1),
            "vertical": cell_str(r, 2),
            "severity": cell_str(r, 3),
            "incident_number": cell_str(r, 4)
        })).collect::<Vec<_>>(),
        "hil_queue": hil_queue_items
    })
}

pub async fn fetch_gpu_observations(db: &DbHandle) -> Value {
    let sql = "SELECT key, value::text, \
               to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
               FROM state_kv WHERE key LIKE 'runtime:gpu-observation:%' \
               ORDER BY updated_at DESC, key DESC LIMIT 50";
    let Ok(res) = db.query_single_readonly(sql).await else {
        return db.not_measured("operations", "/api/v4/operations/gpu", "postgres_unreachable");
    };

    let mut latest_by_gpu: BTreeMap<String, Value> = BTreeMap::new();
    let mut samples: Vec<Value> = Vec::new();

    for row in &res.rows {
        let key = cell_str(row, 0);
        let parsed = parse_json_cell(row, 1);
        let updated_at = cell_str(row, 2);
        let detail = parsed.get("detail").unwrap_or(&parsed);
        let gpu_id = {
            let id = str_field(detail, &["gpu_id"]);
            if id.is_empty() {
                key.clone()
            } else {
                id
            }
        };
        let mem_used = num_field(detail, &["memory_used_mib"]);
        let mem_total = num_field(detail, &["memory_total_mib"]);
        let vram_pct = match (mem_used, mem_total) {
            (Some(u), Some(t)) if t > 0.0 => Some(((u / t) * 1000.0).round() / 10.0),
            _ => None,
        };
        let observed_at = {
            let ts = str_field(detail, &["observed_at"]);
            if ts.is_empty() {
                updated_at.clone()
            } else {
                ts
            }
        };
        let entry = json!({
            "key": key,
            "gpu_id": gpu_id,
            "model": str_field(detail, &["model"]),
            "source": str_field(detail, &["source"]),
            "resource_ref": str_field(detail, &["resource_ref"]),
            "collector_status": str_field(detail, &["collector_status"]),
            "evidence_origin": str_field(detail, &["evidence_origin"]),
            "utilization_pct": num_field(detail, &["utilization_pct"]),
            "temperature_c": num_field(detail, &["temperature_c"]),
            "power_w": num_field(detail, &["power_w"]),
            "power_limit_w": num_field(detail, &["power_limit_w"]).or_else(|| num_field(detail, &["max_power_w"])),
            "queue_depth": num_field(detail, &["queue_depth"]).or_else(|| num_field(detail, &["inference_queue"])),
            "xid_code": num_field(detail, &["xid_code"]),
            "memory_used_mib": mem_used,
            "memory_total_mib": mem_total,
            "vram_pct": vram_pct,
            "finding": detail.get("finding").cloned().unwrap_or(Value::Null),
            "action": detail.get("action").cloned().unwrap_or(Value::Null),
            "agent_path": detail.get("agent_path").cloned().unwrap_or_else(|| json!([])),
            "observed_at": observed_at,
            "updated_at": updated_at
        });
        latest_by_gpu.entry(gpu_id).or_insert_with(|| entry.clone());
        samples.push(entry);
    }

    let nodes: Vec<Value> = latest_by_gpu.into_values().collect();
    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "collector_status": if nodes.is_empty() { "not-measured" } else { "connected" },
        "count": nodes.len(),
        "sample_count": samples.len(),
        "nodes": nodes,
        "samples": samples
    })
}

pub async fn fetch_incidents(db: &DbHandle, limit: Option<usize>) -> Value {
    fetch_incidents_filtered(db, limit, None).await
}

pub async fn fetch_incidents_filtered(
    db: &DbHandle,
    limit: Option<usize>,
    search: Option<&str>,
) -> Value {
    let lim = clamp_limit(limit, 50, 100);
    let where_clause = match search.map(str::trim).filter(|s| !s.is_empty()) {
        Some(q) => {
            let pat = quote_like_contains(q);
            format!(
                "WHERE correlation_id ILIKE {pat} OR COALESCE(canonical_incident_id, '') ILIKE {pat} \
                 OR COALESCE(canonical_incident_number, '') ILIKE {pat} OR COALESCE(search_document, '') ILIKE {pat}"
            )
        }
        None => String::new(),
    };
    let sql = format!(
        "SELECT correlation_id, last_seq, projected_state, projected_vertical, \
         projected_severity, group_history_count, COALESCE(canonical_incident_id, ''), \
         COALESCE(canonical_incident_number, ''), COALESCE(canonical_opened_at, ''), \
         COALESCE(history::text, '[]') \
         FROM operator_incident_projection {where_clause} ORDER BY last_seq DESC LIMIT {lim}"
    );
    let local_inc_sql = "SELECT key, value::text, \
                         to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                         FROM state_kv WHERE key LIKE 'console_v4:operations:incident:%' \
                         ORDER BY updated_at DESC LIMIT 30";
    let local_int_sql = "SELECT key, value::text, \
                         to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                         FROM state_kv WHERE key LIKE 'console_v4:operations:intervention:%' \
                         ORDER BY updated_at DESC LIMIT 50";
    let scope_sql = "SELECT value::text FROM state_kv WHERE key = 'operator-projection:operations:scope.effective' LIMIT 1";

    let (Ok(res), local_inc_res, local_int_res, scope_res) = tokio::join!(
        db.query_single_readonly(&sql),
        db.query_single_readonly(local_inc_sql),
        db.query_single_readonly(local_int_sql),
        db.query_single_readonly(scope_sql),
    ) else {
        return db.not_measured("operations", "/api/v4/operations/incidents", "postgres_unreachable");
    };
    let effective_scope = scope_res
        .ok()
        .and_then(|r| r.rows.first().map(|row| parse_json_cell(row, 0)))
        .unwrap_or(Value::Null);

    let mut interventions_by_corr: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    if let Ok(int_rows) = local_int_res {
        for row in &int_rows.rows {
            let v = parse_json_cell(row, 1);
            let corr = str_field(&v, &["correlation_id"]);
            if !corr.is_empty() {
                interventions_by_corr.entry(corr).or_default().push(json!({
                    "key": cell_str(row, 0),
                    "action": str_field(&v, &["action"]),
                    "reason": str_field(&v, &["reason"]),
                    "actor": str_field(&v, &["actor"]),
                    "recorded_at": cell_str(row, 2)
                }));
            }
        }
    }

    let mut items: Vec<Value> = res
        .rows
        .iter()
        .map(|row| {
            let corr = cell_str(row, 0);
            let history = parse_json_cell(row, 9);
            let first_entry = history
                .as_array()
                .and_then(|arr| arr.first())
                .and_then(|it| it.get("entry"));
            let title = first_entry
                .map(|e| str_field(e, &["title"]))
                .filter(|s| !s.is_empty())
                .unwrap_or_else(|| corr.clone());
            let summary = first_entry
                .map(|e| str_field(e, &["summary"]))
                .unwrap_or_default();
            let actor = history
                .as_array()
                .and_then(|arr| arr.first())
                .map(|it| str_field(it, &["actor"]))
                .unwrap_or_default();
            let extra_interventions = interventions_by_corr
                .get(&corr)
                .cloned()
                .unwrap_or_default();
            json!({
                "correlation_id": corr,
                "last_seq": cell_i64(row, 1),
                "state": cell_str(row, 2),
                "vertical": cell_str(row, 3),
                "severity": cell_str(row, 4),
                "history_count": cell_i64(row, 5),
                "canonical_incident_id": cell_str(row, 6),
                "canonical_incident_number": cell_str(row, 7),
                "opened_at": cell_str(row, 8),
                "title": title,
                "summary": summary,
                "lead_agent": actor,
                "history": history,
                "interventions": extra_interventions
            })
        })
        .collect();

    if let Ok(local_rows) = local_inc_res {
        for row in &local_rows.rows {
            let v = parse_json_cell(row, 1);
            let id = str_field(&v, &["id"]);
            if !id.is_empty() {
                items.push(json!({
                    "correlation_id": id,
                    "last_seq": 0,
                    "state": "in_progress",
                    "vertical": str_field(&v, &["vertical"]),
                    "severity": str_field(&v, &["severity"]),
                    "history_count": 1,
                    "canonical_incident_id": id,
                    "canonical_incident_number": id,
                    "opened_at": cell_str(row, 2),
                    "title": str_field(&v, &["title"]),
                    "summary": str_field(&v, &["summary"]),
                    "subscription": str_field(&v, &["subscription"]),
                    "resource": str_field(&v, &["resource"]),
                    "origin": "human-manual",
                    "lead_agent": "Operator",
                    "history": [],
                    "interventions": []
                }));
            }
        }
    }

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "effective_scope": effective_scope,
        "count": items.len(),
        "items": items
    })
}

pub async fn fetch_hil_queue(db: &DbHandle) -> Value {
    let cnt_sql = "SELECT count(*) FROM state_kv WHERE key LIKE 'hil_park:%'";
    let sql = "SELECT key, value::text, \
               to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
               FROM state_kv WHERE key LIKE 'hil_park:%' ORDER BY updated_at DESC LIMIT 60";
    let dec_sql = "SELECT key, value::text, \
                   to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                   FROM state_kv WHERE key LIKE 'console_v4:operations:hil_decision:%' \
                   ORDER BY updated_at DESC LIMIT 60";
    let audit_sql = "SELECT seq, COALESCE(correlation_id, ''), \
                     COALESCE(entry->>'approval_id', ''), \
                     COALESCE(entry->'payload'->>'resource_id', entry->>'resource_id', entry->>'target_resource_ref', '') \
                     FROM audit_log WHERE action_kind LIKE 'hil.%' OR action_kind LIKE 'approval%' \
                     ORDER BY seq DESC LIMIT 120";
    let (Ok(cnt_res), Ok(res), dec_res, audit_res) = tokio::join!(
        db.query_single_readonly(cnt_sql),
        db.query_single_readonly(sql),
        db.query_single_readonly(dec_sql),
        db.query_single_readonly(audit_sql),
    ) else {
        return db.not_measured("operations", "/api/v4/operations/hil-queue", "postgres_unreachable");
    };

    let mut audit_seq_by_corr: BTreeMap<String, i64> = BTreeMap::new();
    let mut audit_seq_by_approval: BTreeMap<String, i64> = BTreeMap::new();
    let mut audit_seq_by_target: BTreeMap<String, i64> = BTreeMap::new();
    if let Ok(arows) = audit_res {
        for r in &arows.rows {
            if let Some(seq) = cell_i64(r, 0) {
                let corr = cell_str(r, 1);
                if !corr.is_empty() {
                    audit_seq_by_corr.entry(corr).or_insert(seq);
                }
                let appr = cell_str(r, 2);
                if !appr.is_empty() {
                    audit_seq_by_approval.entry(appr).or_insert(seq);
                }
                let tgt = cell_str(r, 3);
                if !tgt.is_empty() {
                    audit_seq_by_target.entry(tgt).or_insert(seq);
                }
            }
        }
    }

    let total_count = cnt_res
        .rows
        .first()
        .and_then(|r| cell_i64(r, 0))
        .unwrap_or(0);

    let mut decisions_map: BTreeMap<String, Value> = BTreeMap::new();
    if let Ok(drows) = dec_res {
        for r in &drows.rows {
            let v = parse_json_cell(r, 1);
            let aid = str_field(&v, &["approval_id"]);
            if !aid.is_empty() {
                decisions_map.insert(
                    aid,
                    json!({
                        "decision": str_field(&v, &["decision"]),
                        "reason": str_field(&v, &["reason"]),
                        "actor": str_field(&v, &["actor"]),
                        "recorded_at": cell_str(r, 2)
                    }),
                );
            }
        }
    }

    let items: Vec<Value> = res
        .rows
        .iter()
        .map(|row| {
            let key = cell_str(row, 0);
            let parsed = parse_json_cell(row, 1);
            let updated_at = cell_str(row, 2);
            let approval_id = {
                let id = str_field(&parsed, &["approval_id"]);
                if id.is_empty() {
                    key.strip_prefix("hil_park:").unwrap_or(&key).to_string()
                } else {
                    id
                }
            };
            let local_decision = decisions_map.get(&approval_id).cloned().unwrap_or(Value::Null);
            let status = if !local_decision.is_null() {
                str_field(&local_decision, &["decision"])
            } else {
                str_field(&parsed, &["status"])
            };
            let correlation_id = str_field(&parsed, &["correlation_id"]);
            let target_ref = str_field(&parsed, &["action", "target_resource_ref"]);
            let audit_seq = audit_seq_by_approval
                .get(&approval_id)
                .copied()
                .or_else(|| audit_seq_by_corr.get(&correlation_id).copied())
                .or_else(|| audit_seq_by_target.get(&target_ref).copied());
            json!({
                "key": key,
                "approval_id": approval_id,
                "audit_seq": audit_seq,
                "rule_id": str_field(&parsed, &["rule_id"]),
                "category": str_field(&parsed, &["category"]),
                "severity": str_field(&parsed, &["severity"]),
                "status": if status.is_empty() { "pending".to_string() } else { status },
                "action_type": str_field(&parsed, &["action_type"]),
                "mode": str_field(&parsed, &["action", "mode"]),
                "target_resource_ref": target_ref,
                "correlation_id": correlation_id,
                "submitter_oid": str_field(&parsed, &["submitter_oid"]),
                "parked_at": str_field(&parsed, &["parked_at"]),
                "quorum_required": str_field(&parsed, &["effective_quorum_required"]),
                "idempotency_key": str_field(&parsed, &["idempotency_key"]),
                "rollback_ref": str_field(&parsed, &["action", "rollback_ref"]),
                "stop_condition": parsed.pointer("/action/stop_condition").cloned().unwrap_or(Value::Null),
                "blast_radius": parsed.pointer("/action/blast_radius").cloned().unwrap_or(Value::Null),
                "approval_context": parsed.get("approval_context").cloned().unwrap_or(Value::Null),
                "local_decision": local_decision,
                "updated_at": updated_at
            })
        })
        .collect();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "total_count": total_count,
        "count": items.len(),
        "items": items
    })
}

pub(crate) fn normalize_security_priority(severity: &str) -> &'static str {
    match severity.trim().to_ascii_lowercase().as_str() {
        "critical" => "P0",
        "high" => "P1",
        "medium" => "P2",
        "low" | "info" | "clear" => "P3",
        _ => "TBD",
    }
}

pub(crate) fn security_severity_rank(severity: &str) -> u8 {
    match severity.trim().to_ascii_lowercase().as_str() {
        "critical" => 0,
        "high" => 1,
        "medium" => 2,
        "undetermined" => 3,
        "low" | "info" => 4,
        _ => 5,
    }
}

pub(crate) fn infer_code_ecosystem(file_path: &str) -> &'static str {
    let lower = file_path.trim().to_ascii_lowercase();
    if lower.is_empty() {
        return "Container/Deps";
    }
    let file_name = lower.rsplit('/').next().unwrap_or(&lower);
    if file_name.starts_with("dockerfile") || file_name.ends_with(".dockerfile") {
        "Dockerfile"
    } else if file_name == "requirements.txt"
        || (file_name.starts_with("requirements") && file_name.ends_with(".txt"))
        || file_name == "pyproject.toml"
        || file_name == "poetry.lock"
        || file_name == "uv.lock"
        || file_name.ends_with(".py")
    {
        "Python"
    } else if file_name == "package-lock.json"
        || file_name == "package.json"
        || file_name == "yarn.lock"
        || file_name == "pnpm-lock.yaml"
        || file_name.ends_with(".ts")
        || file_name.ends_with(".tsx")
        || file_name.ends_with(".js")
        || file_name.ends_with(".jsx")
    {
        "Node.js"
    } else if file_name == "go.mod" || file_name == "go.sum" || file_name.ends_with(".go") {
        "Go"
    } else if file_name == "cargo.toml" || file_name == "cargo.lock" || file_name.ends_with(".rs") {
        "Rust"
    } else if file_name.ends_with(".tf") || file_name.ends_with(".tfvars") || file_name.ends_with(".hcl") {
        "Terraform"
    } else if file_name.ends_with(".yaml") || file_name.ends_with(".yml") {
        "Kubernetes YAML"
    } else if file_name == "pom.xml" || file_name.starts_with("build.gradle") || file_name.ends_with(".java") {
        "Java"
    } else if file_name.ends_with(".csproj") || file_name == "packages.lock.json" || file_name.ends_with(".cs") {
        ".NET"
    } else {
        "Container/Deps"
    }
}

pub(crate) fn extract_cvss_score(rationale: &str) -> Option<f64> {
    if !rationale.to_ascii_lowercase().contains("cvss") {
        return None;
    }
    let mut best: Option<f64> = None;
    for token in rationale.split(|c: char| c.is_whitespace() || c == ',' || c == ';') {
        if let Some((_, rhs)) = token.split_once('=') {
            let cleaned = rhs.trim_matches(|c: char| !c.is_ascii_digit() && c != '.');
            if let Ok(v) = cleaned.parse::<f64>() {
                if (0.0..=10.0).contains(&v) {
                    best = Some(best.map_or(v, |prev| prev.max(v)));
                }
            }
        }
    }
    best
}

fn derive_package_from_code_context(code_context: &Value, file_path: &str) -> Option<String> {
    if code_context.get("redacted").and_then(Value::as_bool).unwrap_or(false) {
        return None;
    }
    let lines = code_context.get("lines").and_then(Value::as_array)?;
    let hi_start = code_context.get("highlight_start").and_then(Value::as_i64)?;
    let hi_end = code_context
        .get("highlight_end")
        .and_then(Value::as_i64)
        .unwrap_or(hi_start);
    let hi_texts: Vec<&str> = lines
        .iter()
        .filter_map(|ln| {
            let num = ln.get("number").and_then(Value::as_i64)?;
            if num >= hi_start && num <= hi_end {
                ln.get("text").and_then(Value::as_str).map(str::trim)
            } else {
                None
            }
        })
        .collect();
    if hi_texts.is_empty() {
        return None;
    }
    let lower_path = file_path.to_ascii_lowercase();
    if lower_path.contains("requirements") && lower_path.ends_with(".txt") {
        let first = hi_texts[0];
        if !first.is_empty() && !first.starts_with('#') && (first.contains("==") || first.contains(">=") || first.contains("~=")) {
            return Some(first.to_string());
        }
    }
    if lower_path.ends_with("package-lock.json") {
        let mut pkg_name: Option<String> = None;
        let mut version: Option<String> = None;
        for txt in &hi_texts {
            if pkg_name.is_none() {
                if let Some(idx) = txt.find("node_modules/") {
                    let rest = &txt[idx + "node_modules/".len()..];
                    if let Some(end_q) = rest.find('"') {
                        let name = rest[..end_q].trim();
                        if !name.is_empty() {
                            pkg_name = Some(name.to_string());
                        }
                    }
                }
            }
            if version.is_none() && txt.starts_with("\"version\"") {
                if let Some((_, rhs)) = txt.split_once(':') {
                    let v = rhs.trim().trim_end_matches(',').trim_matches('"');
                    if !v.is_empty() {
                        version = Some(v.to_string());
                    }
                }
            }
        }
        if let Some(name) = pkg_name {
            return Some(match version {
                Some(v) => format!("{name}@{v}"),
                None => name,
            });
        }
    }
    None
}

fn sanitize_code_context(raw: Option<&Value>, rule_id: &str) -> Value {
    let Some(ctx) = raw.filter(|v| v.is_object()) else {
        return Value::Null;
    };
    let is_secret_rule = rule_id.to_ascii_lowercase().contains("gitleaks")
        || rule_id.to_ascii_lowercase().contains("secret");
    let redacted = ctx.get("redacted").and_then(Value::as_bool).unwrap_or(false);
    if is_secret_rule && !redacted {
        return json!({
            "start_line": ctx.get("start_line").cloned().unwrap_or(Value::Null),
            "highlight_start": ctx.get("highlight_start").cloned().unwrap_or(Value::Null),
            "highlight_end": ctx.get("highlight_end").cloned().unwrap_or(Value::Null),
            "redacted": true,
            "lines": []
        });
    }
    ctx.clone()
}

pub async fn fetch_security(db: &DbHandle) -> Value {
    let cs_sql = "SELECT key, value::text, \
                  to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                  FROM state_kv WHERE key LIKE 'runtime:code-security-issues:%' \
                  AND key NOT LIKE '%:artifacts%' ORDER BY updated_at DESC LIMIT 10";
    let art_sql = "SELECT key, value::jsonb->>'sarif', \
                   to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                   FROM state_kv WHERE key LIKE 'runtime:code-security-issues:%:artifacts%' \
                   ORDER BY updated_at DESC LIMIT 10";
    let find_sql = "SELECT key, value::text, \
                    to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                    FROM state_kv WHERE key LIKE 'runtime:analyzer-finding-current:%' \
                    ORDER BY updated_at DESC LIMIT 40";
    let bl_sql = "SELECT value::text, \
                  to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                  FROM state_kv WHERE key = 'baseline-evaluation:latest:coverage' LIMIT 1";
    let (Ok(cs), art_res, Ok(find), Ok(bl)) = tokio::join!(
        db.query_single_readonly(cs_sql),
        db.query_single_readonly(art_sql),
        db.query_single_readonly(find_sql),
        db.query_single_readonly(bl_sql),
    ) else {
        return db.not_measured("operations", "/api/v4/operations/security", "postgres_unreachable");
    };

    let mut summary_by_id: BTreeMap<String, (String, String, String, Map<String, Value>)> =
        BTreeMap::new();
    for row in &cs.rows {
        let key = cell_str(row, 0);
        let parsed = parse_json_cell(row, 1);
        let updated_at = cell_str(row, 2);
        let mut parts = key.split(':');
        let repo_name = parts.nth(2).unwrap_or("repository").to_string();
        let commit_sha = parts.next().unwrap_or("").to_string();
        if let Some(arr) = parsed.get("issues").and_then(Value::as_array) {
            for item in arr {
                if let Some(obj) = item.as_object() {
                    let iid = obj
                        .get("issue_id")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_string();
                    if !iid.is_empty() {
                        summary_by_id
                            .entry(iid)
                            .or_insert_with(|| (repo_name.clone(), commit_sha.clone(), updated_at.clone(), obj.clone()));
                    }
                }
            }
        }
    }

    let mut seen_ids: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
    let mut code_issues: Vec<Value> = Vec::new();

    if let Ok(art) = art_res {
        for row in &art.rows {
            let key = cell_str(row, 0);
            let sarif_raw = cell_str(row, 1);
            let updated_at = cell_str(row, 2);
            if sarif_raw.is_empty() {
                continue;
            }
            let Ok(sarif) = serde_json::from_str::<Value>(&sarif_raw) else {
                continue;
            };
            let mut parts = key.split(':');
            let repo_name = parts.nth(2).unwrap_or("repository").to_string();
            let commit_sha = parts.next().unwrap_or("").to_string();
            let Some(results) = sarif
                .pointer("/runs/0/results")
                .and_then(Value::as_array)
            else {
                continue;
            };
            for res in results.iter().take(300) {
                let props = res.get("properties").and_then(Value::as_object);
                let iid = props
                    .and_then(|p| p.get("issue_id"))
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string();
                if iid.is_empty() || !seen_ids.insert(iid.clone()) {
                    continue;
                }
                let summary_entry = summary_by_id.get(&iid);
                let rule_id = res
                    .get("ruleId")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string();
                let file_path = res
                    .pointer("/locations/0/physicalLocation/artifactLocation/uri")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string();
                let start_line = res
                    .pointer("/locations/0/physicalLocation/region/startLine")
                    .and_then(Value::as_i64);
                let sev = props
                    .and_then(|p| p.get("severity"))
                    .and_then(Value::as_str)
                    .or_else(|| {
                        summary_entry
                            .and_then(|(_, _, _, m)| m.get("severity"))
                            .and_then(Value::as_str)
                    })
                    .unwrap_or("undetermined")
                    .to_ascii_lowercase();
                let raw_priority = props
                    .and_then(|p| p.get("priority"))
                    .and_then(Value::as_str)
                    .or_else(|| {
                        summary_entry
                            .and_then(|(_, _, _, m)| m.get("priority"))
                            .and_then(Value::as_str)
                    })
                    .unwrap_or("")
                    .to_string();
                let norm_priority = normalize_security_priority(&sev);
                let rationale = props
                    .and_then(|p| p.get("severity_rationale"))
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string();
                let cvss_score = extract_cvss_score(&rationale);
                let code_ctx = sanitize_code_context(props.and_then(|p| p.get("code_context")), &rule_id);
                let explicit_pkg = props
                    .and_then(|p| p.get("package"))
                    .and_then(Value::as_str)
                    .map(str::to_string)
                    .or_else(|| {
                        summary_entry
                            .and_then(|(_, _, _, m)| m.get("package"))
                            .and_then(Value::as_str)
                            .map(str::to_string)
                    });
                let (pkg_val, pkg_inferred) = if let Some(p) = explicit_pkg {
                    (Some(p), false)
                } else if let Some(p) = derive_package_from_code_context(&code_ctx, &file_path) {
                    (Some(p), true)
                } else {
                    (None, false)
                };
                let weakness_class = summary_entry
                    .and_then(|(_, _, _, m)| m.get("weakness_class"))
                    .and_then(Value::as_str)
                    .map(str::to_string)
                    .unwrap_or_else(|| {
                        if rule_id.is_empty() {
                            "vulnerable_dependency".to_string()
                        } else {
                            rule_id.clone()
                        }
                    });
                let due_days = summary_entry
                    .and_then(|(_, _, _, m)| m.get("due_days"))
                    .cloned()
                    .unwrap_or(Value::Null);
                let obs_at = summary_entry
                    .map(|(_, _, ts, _)| ts.clone())
                    .filter(|s| !s.is_empty())
                    .unwrap_or_else(|| updated_at.clone());
                let sarif_title = props
                    .and_then(|p| p.get("title"))
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string();

                let mut obj = Map::new();
                obj.insert("issue_id".to_string(), json!(iid));
                obj.insert("repo".to_string(), json!(repo_name));
                obj.insert("commit_sha".to_string(), json!(commit_sha));
                obj.insert("observed_at".to_string(), json!(obs_at));
                obj.insert("severity".to_string(), json!(sev));
                obj.insert("priority".to_string(), json!(norm_priority));
                obj.insert("raw_priority".to_string(), json!(raw_priority));
                obj.insert("rule_id".to_string(), json!(rule_id));
                obj.insert("weakness_class".to_string(), json!(weakness_class));
                obj.insert("sarif_title".to_string(), json!(sarif_title));
                obj.insert("file_path".to_string(), json!(file_path));
                obj.insert("start_line".to_string(), json!(start_line));
                obj.insert("language".to_string(), json!(infer_code_ecosystem(&file_path)));
                obj.insert("package".to_string(), json!(pkg_val));
                obj.insert("package_inferred_from_context".to_string(), json!(pkg_inferred));
                obj.insert("due_days".to_string(), due_days);
                obj.insert("cvss_score".to_string(), json!(cvss_score));
                obj.insert("severity_rationale".to_string(), json!(rationale));
                obj.insert(
                    "severity_floor".to_string(),
                    props.and_then(|p| p.get("severity_floor")).cloned().unwrap_or(Value::Null),
                );
                obj.insert(
                    "severity_ceiling".to_string(),
                    props.and_then(|p| p.get("severity_ceiling")).cloned().unwrap_or(Value::Null),
                );
                obj.insert(
                    "deciding_facts".to_string(),
                    props.and_then(|p| p.get("deciding_facts")).cloned().unwrap_or_else(|| json!([])),
                );
                obj.insert(
                    "confidence".to_string(),
                    props.and_then(|p| p.get("confidence")).cloned().unwrap_or_else(|| json!("reported")),
                );
                obj.insert(
                    "cwe_ids".to_string(),
                    props.and_then(|p| p.get("cwe_ids")).cloned().unwrap_or_else(|| json!([])),
                );
                obj.insert(
                    "advisory_ids".to_string(),
                    props.and_then(|p| p.get("advisory_ids")).cloned().unwrap_or_else(|| json!([])),
                );
                obj.insert(
                    "producers".to_string(),
                    props.and_then(|p| p.get("producers")).cloned().unwrap_or_else(|| json!([])),
                );
                obj.insert(
                    "known_exploited".to_string(),
                    props.and_then(|p| p.get("known_exploited")).cloned().unwrap_or_else(|| json!(false)),
                );
                obj.insert("code_context".to_string(), code_ctx);
                obj.insert(
                    "flow_steps".to_string(),
                    props.and_then(|p| p.get("flow_steps")).cloned().unwrap_or_else(|| json!([])),
                );
                code_issues.push(Value::Object(obj));
            }
        }
    }

    // Fallback: include any summary issues whose SARIF artifact was not present.
    for (iid, (repo_name, commit_sha, updated_at, raw_obj)) in &summary_by_id {
        if !seen_ids.insert(iid.clone()) {
            continue;
        }
        let mut obj = raw_obj.clone();
        let sev = obj
            .get("severity")
            .and_then(Value::as_str)
            .unwrap_or("undetermined")
            .to_ascii_lowercase();
        let raw_priority = obj
            .get("priority")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        obj.insert("repo".to_string(), json!(repo_name));
        obj.insert("commit_sha".to_string(), json!(commit_sha));
        obj.insert("observed_at".to_string(), json!(updated_at));
        obj.insert("severity".to_string(), json!(sev));
        obj.insert("priority".to_string(), json!(normalize_security_priority(&sev)));
        obj.insert("raw_priority".to_string(), json!(raw_priority));
        obj.insert("language".to_string(), json!("Container/Deps"));
        code_issues.push(Value::Object(obj));
    }

    code_issues.sort_by(|a, b| {
        let sa = a.get("severity").and_then(Value::as_str).unwrap_or("");
        let sb = b.get("severity").and_then(Value::as_str).unwrap_or("");
        let ra = security_severity_rank(sa);
        let rb = security_severity_rank(sb);
        let ca = a.get("cvss_score").and_then(Value::as_f64).unwrap_or(-1.0);
        let cb = b.get("cvss_score").and_then(Value::as_f64).unwrap_or(-1.0);
        let ia = a.get("issue_id").and_then(Value::as_str).unwrap_or("");
        let ib = b.get("issue_id").and_then(Value::as_str).unwrap_or("");
        ra.cmp(&rb)
            .then_with(|| cb.partial_cmp(&ca).unwrap_or(std::cmp::Ordering::Equal))
            .then_with(|| ia.cmp(ib))
    });

    let mut sev_critical: usize = 0;
    let mut sev_high: usize = 0;
    let mut sev_medium: usize = 0;
    let mut sev_low: usize = 0;
    let mut sev_undetermined: usize = 0;
    for item in &code_issues {
        match item.get("severity").and_then(Value::as_str).unwrap_or("") {
            "critical" => sev_critical += 1,
            "high" => sev_high += 1,
            "medium" => sev_medium += 1,
            "low" | "info" => sev_low += 1,
            _ => sev_undetermined += 1,
        }
    }

    let analyzer_findings: Vec<Value> = find
        .rows
        .iter()
        .map(|r| {
            let v = parse_json_cell(r, 1);
            json!({
                "key": cell_str(r, 0),
                "finding_id": str_field(&v, &["finding_id"]),
                "signal": str_field(&v, &["signal"]),
                "status": str_field(&v, &["status"]),
                "severity": str_field(&v, &["severity"]),
                "assessed_by": str_field(&v, &["assessed_by"]),
                "observation": str_field(&v, &["observation"]),
                "resource_ref": str_field(&v, &["resource_ref"]),
                "occurred_at": str_field(&v, &["occurred_at"]),
                "updated_at": cell_str(r, 2)
            })
        })
        .collect();

    let baseline_summary = bl
        .rows
        .first()
        .map(|r| parse_json_cell(r, 0))
        .unwrap_or(Value::Null);

    let latest_observed_at = cs
        .rows
        .first()
        .map(|r| cell_str(r, 2))
        .unwrap_or_default();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "latest_observed_at": latest_observed_at,
        "code_security_count": code_issues.len(),
        "severity_counts": {
            "critical": sev_critical,
            "high": sev_high,
            "medium": sev_medium,
            "low": sev_low,
            "undetermined": sev_undetermined,
            "total": code_issues.len()
        },
        "code_security_issues": code_issues,
        "analyzer_findings_count": analyzer_findings.len(),
        "analyzer_findings": analyzer_findings,
        "baseline_coverage": baseline_summary
    })
}

pub async fn fetch_baselines(db: &DbHandle) -> Value {
    let latest_sql = "SELECT value::text, \
                      to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                      FROM state_kv WHERE key = 'baseline-evaluation:latest:coverage' LIMIT 1";
    let outcomes_sql = "SELECT key, value::text, \
                        to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                        FROM state_kv WHERE key LIKE 'baseline-evaluation:outcomes:%' \
                        ORDER BY updated_at DESC LIMIT 60";
    let drift_sql = "SELECT key, value::text, \
                     to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                     FROM state_kv WHERE key LIKE 'hil_park:%' \
                     AND value->>'category' = 'config_drift' \
                     ORDER BY updated_at DESC LIMIT 60";
    let snap_sql = "SELECT id, status, source, COALESCE(resource_count, 0), COALESCE(link_count, 0), \
                    COALESCE(to_char(completed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') \
                    FROM inventory_snapshot ORDER BY started_at DESC LIMIT 1";
    let (Ok(latest), Ok(outcomes), drift_res, snap_res) = tokio::join!(
        db.query_single_readonly(latest_sql),
        db.query_single_readonly(outcomes_sql),
        db.query_single_readonly(drift_sql),
        db.query_single_readonly(snap_sql),
    ) else {
        return db.not_measured("operations", "/api/v4/operations/baselines", "postgres_unreachable");
    };

    let mut coverage = latest
        .rows
        .first()
        .map(|r| parse_json_cell(r, 0))
        .unwrap_or(Value::Null);
    let mut updated_at = latest
        .rows
        .first()
        .map(|r| cell_str(r, 1))
        .unwrap_or_default();

    let mut items: Vec<Value> = outcomes
        .rows
        .iter()
        .map(|r| {
            let v = parse_json_cell(r, 1);
            json!({
                "key": cell_str(r, 0),
                "outcome": str_field(&v, &["outcome"]),
                "rule_ref": str_field(&v, &["rule_ref"]),
                "reason_code": str_field(&v, &["reason_code"]),
                "resource_ref": str_field(&v, &["resource_ref"]),
                "generation_id": str_field(&v, &["generation_id"]),
                "evaluated_at": str_field(&v, &["evaluated_at"]),
                "updated_at": cell_str(r, 2)
            })
        })
        .collect();

    let active_snapshot = snap_res.ok().and_then(|res| {
        res.rows.first().map(|r| {
            json!({
                "snapshot_id": cell_str(r, 0),
                "status": cell_str(r, 1),
                "source": cell_str(r, 2),
                "resource_count": cell_i64(r, 3).unwrap_or(0),
                "link_count": cell_i64(r, 4).unwrap_or(0),
                "completed_at": cell_str(r, 5)
            })
        })
    });

    // When historical baseline-evaluation records were pruned by the 7-day retention window,
    // surface active 7-day config_drift findings from hil_park:* + active inventory snapshot.
    if items.is_empty() {
        if let Ok(drift_rows) = drift_res {
            let gen_id = active_snapshot
                .as_ref()
                .and_then(|s| s.get("snapshot_id"))
                .and_then(Value::as_str)
                .unwrap_or("snapshot-7d-active")
                .to_string();
            for r in &drift_rows.rows {
                let v = parse_json_cell(r, 1);
                let ts = cell_str(r, 2);
                if updated_at.is_empty() {
                    updated_at = ts.clone();
                }
                items.push(json!({
                    "key": cell_str(r, 0),
                    "outcome": "violated",
                    "rule_ref": format!("rule:{}", str_field(&v, &["rule_id"])),
                    "reason_code": str_field(&v, &["category"]),
                    "resource_ref": str_field(&v, &["action", "target_resource_ref"]),
                    "generation_id": gen_id,
                    "evaluated_at": str_field(&v, &["parked_at"]),
                    "severity": str_field(&v, &["severity"]),
                    "action_type": str_field(&v, &["action_type"]),
                    "updated_at": ts
                }));
            }
        }
        if coverage.is_null() {
            let res_total = active_snapshot
                .as_ref()
                .and_then(|s| s.get("resource_count"))
                .and_then(Value::as_i64)
                .unwrap_or(0);
            let violated = i64::try_from(items.len()).unwrap_or(0);
            let compliant = (res_total - violated).max(0);
            coverage = json!({
                "window_days": 7,
                "source_basis": "7d_config_drift_and_active_snapshot",
                "compliant_count": compliant,
                "violated_count": violated,
                "abstained_count": 0,
                "complete": true,
                "generation_id": active_snapshot
                    .as_ref()
                    .and_then(|s| s.get("snapshot_id"))
                    .and_then(Value::as_str)
                    .unwrap_or("7d-active")
            });
        }
    }

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "window_days": 7,
        "coverage": coverage,
        "coverage_updated_at": updated_at,
        "active_snapshot": active_snapshot,
        "count": items.len(),
        "items": items
    })
}

pub async fn fetch_alert_quality(db: &DbHandle) -> Value {
    let aq_sql = "SELECT key, value::text, \
                  to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                  FROM state_kv WHERE key LIKE 'operator-alert-quality:%' \
                  ORDER BY updated_at DESC LIMIT 30";
    let find_sql = "SELECT key, value::text, \
                    to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                    FROM state_kv WHERE key LIKE 'runtime:analyzer-finding-current:%' \
                    ORDER BY updated_at DESC LIMIT 20";
    let scope_sql = "SELECT value::text FROM state_kv WHERE key = 'operator-projection:operations:scope.effective' LIMIT 1";
    let (Ok(aq), Ok(find), scope_res) = tokio::join!(
        db.query_single_readonly(aq_sql),
        db.query_single_readonly(find_sql),
        db.query_single_readonly(scope_sql),
    ) else {
        return db.not_measured(
            "operations",
            "/api/v4/operations/alert-quality",
            "postgres_unreachable",
        );
    };
    let effective_scope = scope_res
        .ok()
        .and_then(|r| r.rows.first().map(|row| parse_json_cell(row, 0)))
        .unwrap_or(Value::Null);

    let mut latest_index: Value = Value::Null;
    let mut reports: Vec<Value> = Vec::new();
    let mut plans: Vec<Value> = Vec::new();

    for row in &aq.rows {
        let key = cell_str(row, 0);
        let parsed = parse_json_cell(row, 1);
        let updated_at = cell_str(row, 2);
        if key.contains(":index:") {
            if latest_index.is_null() {
                latest_index = json!({ "key": key, "updated_at": updated_at, "payload": parsed });
            }
        } else if key.contains(":report:") {
            reports.push(json!({ "key": key, "updated_at": updated_at, "payload": parsed }));
        } else if key.contains(":plan:") {
            plans.push(json!({ "key": key, "updated_at": updated_at, "payload": parsed }));
        }
    }

    let findings: Vec<Value> = find
        .rows
        .iter()
        .map(|r| {
            let v = parse_json_cell(r, 1);
            json!({
                "finding_id": str_field(&v, &["finding_id"]),
                "signal": str_field(&v, &["signal"]),
                "severity": str_field(&v, &["severity"]),
                "status": str_field(&v, &["status"]),
                "observation": str_field(&v, &["observation"]),
                "resource_ref": str_field(&v, &["resource_ref"]),
                "updated_at": cell_str(r, 2)
            })
        })
        .collect();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "effective_scope": effective_scope,
        "latest_index": latest_index,
        "report_count": reports.len(),
        "plan_count": plans.len(),
        "reports": reports,
        "plans": plans,
        "analyzer_findings": findings
    })
}

pub async fn fetch_detection_readiness(db: &DbHandle) -> Value {
    let cov_sql = "SELECT state_type, source_identity, count(*)::bigint, \
                   SUM(CASE WHEN complete THEN 1 ELSE 0 END)::bigint, \
                   COALESCE(MAX(limitation), ''), \
                   to_char(MAX(recorded_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                   FROM operational_state_transition_coverage \
                   GROUP BY state_type, source_identity ORDER BY 3 DESC LIMIT 30";
    let kube_sql = "SELECT cluster_ref, sequence, COALESCE(limitation, ''), \
                    COALESCE(to_char(coverage_through_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), ''), \
                    to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                    FROM kubernetes_lifecycle_cursor ORDER BY updated_at DESC LIMIT 20";
    let camp_sql = "SELECT key, value::text, \
                    to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                    FROM state_kv WHERE key LIKE 'observation-campaign:source:%' ORDER BY key LIMIT 20";
    let (Ok(cov), Ok(kube), Ok(camp)) = tokio::join!(
        db.query_single_readonly(cov_sql),
        db.query_single_readonly(kube_sql),
        db.query_single_readonly(camp_sql),
    ) else {
        return db.not_measured(
            "operations",
            "/api/v4/operations/detection-readiness",
            "postgres_unreachable",
        );
    };

    let coverage_groups: Vec<Value> = cov
        .rows
        .iter()
        .map(|r| {
            let total = cell_i64(r, 2).unwrap_or(0);
            let complete = cell_i64(r, 3).unwrap_or(0);
            json!({
                "state_type": cell_str(r, 0),
                "source_identity": cell_str(r, 1),
                "total": total,
                "complete": complete,
                "limitation": cell_str(r, 4),
                "last_recorded_at": cell_str(r, 5)
            })
        })
        .collect();

    let kubernetes_cursors: Vec<Value> = kube
        .rows
        .iter()
        .map(|r| {
            json!({
                "cluster_ref": cell_str(r, 0),
                "sequence": cell_i64(r, 1).unwrap_or(0),
                "limitation": cell_str(r, 2),
                "coverage_through_at": cell_str(r, 3),
                "updated_at": cell_str(r, 4)
            })
        })
        .collect();

    let observation_sources: Vec<Value> = camp
        .rows
        .iter()
        .map(|r| {
            let v = parse_json_cell(r, 1);
            json!({
                "source_id": str_field(&v, &["source_id"]),
                "domain": str_field(&v, &["domain"]),
                "status": str_field(&v, &["status"]),
                "coverage": str_field(&v, &["coverage"]),
                "freshness": str_field(&v, &["freshness"]),
                "owner_agent": str_field(&v, &["owner_agent"]),
                "duration_ms": num_field(&v, &["duration_ms"]),
                "reason_codes": v.get("reason_codes").cloned().unwrap_or_else(|| json!([])),
                "updated_at": cell_str(r, 2)
            })
        })
        .collect();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "coverage_groups": coverage_groups,
        "kubernetes_cursors": kubernetes_cursors,
        "observation_sources": observation_sources
    })
}

pub async fn fetch_conversation_delivery(db: &DbHandle) -> Value {
    let dlv_sql = "SELECT delivery_id, channel_kind, state, attempt_count, \
                   COALESCE(scope_ref, ''), COALESCE(conversation_id, ''), \
                   COALESCE(last_error_code, ''), duplicate_risk, \
                   to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
                   COALESCE(to_char(terminal_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') \
                   FROM conversation_outbound_delivery ORDER BY created_at DESC LIMIT 50";
    let brk_sql = "SELECT adapter_id, channel_kind, mode, revision, COALESCE(reason, ''), \
                   to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                   FROM conversation_adapter_breaker ORDER BY adapter_id LIMIT 20";
    let (Ok(dlv), Ok(brk)) = tokio::join!(
        db.query_single_readonly(dlv_sql),
        db.query_single_readonly(brk_sql),
    ) else {
        return db.not_measured(
            "operations",
            "/api/v4/operations/conversation-delivery",
            "postgres_unreachable",
        );
    };

    let deliveries: Vec<Value> = dlv
        .rows
        .iter()
        .map(|r| {
            json!({
                "delivery_id": cell_str(r, 0),
                "channel_kind": cell_str(r, 1),
                "state": cell_str(r, 2),
                "attempt_count": cell_i64(r, 3).unwrap_or(0),
                "scope_ref": cell_str(r, 4),
                "conversation_id": cell_str(r, 5),
                "last_error_code": cell_str(r, 6),
                "duplicate_risk": cell_str(r, 7) == "t" || cell_str(r, 7) == "true",
                "created_at": cell_str(r, 8),
                "terminal_at": cell_str(r, 9)
            })
        })
        .collect();

    let breakers: Vec<Value> = brk
        .rows
        .iter()
        .map(|r| {
            json!({
                "adapter_id": cell_str(r, 0),
                "channel_kind": cell_str(r, 1),
                "mode": cell_str(r, 2),
                "revision": cell_i64(r, 3).unwrap_or(0),
                "reason": cell_str(r, 4),
                "updated_at": cell_str(r, 5)
            })
        })
        .collect();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "count": deliveries.len(),
        "items": deliveries,
        "breakers": breakers
    })
}

pub async fn fetch_workflows_and_processes(db: &DbHandle) -> Value {
    let wf_sql = "SELECT definition_id, workflow_name, workflow_version, lifecycle, origin, \
                  COALESCE(visibility, ''), COALESCE(owner_ref, ''), \
                  to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                  FROM workflow_definition ORDER BY created_at DESC LIMIT 100";
    let pr_sql = "SELECT process_id, workflow_ref, COALESCE(workflow_version, ''), status, \
                  COALESCE(current_step, ''), COALESCE(target_resource_id, ''), \
                  COALESCE(correlation_id, ''), revision, \
                  to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
                  to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                  FROM process_runtime ORDER BY updated_at DESC LIMIT 100";
    let ev_sql = "SELECT seq, event_id, process_id, kind, COALESCE(step_id, ''), attempt, \
                  to_char(recorded_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
                  COALESCE(payload::text, '{}') \
                  FROM process_event ORDER BY seq DESC LIMIT 60";
    let bp_sql = "SELECT candidate_id, normalized_task_intent, schedule_class, \
                  COALESCE(schedule_expression, ''), state, enabled, shadow_only, \
                  COALESCE(confidence::text, ''), COALESCE(proposer, ''), \
                  COALESCE(resource_scope, ''), COALESCE(estimated_cost_microusd, 0), \
                  COALESCE(required_tools::text, '[]'), COALESCE(isolation_profile::text, '{}') \
                  FROM automation_blueprint_candidate ORDER BY created_at DESC LIMIT 50";
    let app_sql = "SELECT value::text FROM state_kv WHERE key = 'operator-projection:operations:process.apps' LIMIT 1";

    let (Ok(wf), Ok(pr), Ok(ev), Ok(bp), Ok(apps)) = tokio::join!(
        db.query_single_readonly(wf_sql),
        db.query_single_readonly(pr_sql),
        db.query_single_readonly(ev_sql),
        db.query_single_readonly(bp_sql),
        db.query_single_readonly(app_sql),
    ) else {
        return db.not_measured("operations", "/api/v4/operations/automation", "postgres_unreachable");
    };

    let process_apps = apps
        .rows
        .first()
        .map(|r| parse_json_cell(r, 0))
        .unwrap_or(Value::Null);

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "process_apps": process_apps,
        "workflows": wf.rows.iter().map(|r| json!({
            "definition_id": cell_str(r, 0),
            "name": cell_str(r, 1),
            "version": cell_str(r, 2),
            "lifecycle": cell_str(r, 3),
            "origin": cell_str(r, 4),
            "visibility": cell_str(r, 5),
            "owner_ref": cell_str(r, 6),
            "created_at": cell_str(r, 7)
        })).collect::<Vec<_>>(),
        "processes": pr.rows.iter().map(|r| json!({
            "process_id": cell_str(r, 0),
            "workflow_ref": cell_str(r, 1),
            "workflow_version": cell_str(r, 2),
            "status": cell_str(r, 3),
            "current_step": cell_str(r, 4),
            "target_resource_id": cell_str(r, 5),
            "correlation_id": cell_str(r, 6),
            "revision": cell_i64(r, 7).unwrap_or(0),
            "started_at": cell_str(r, 8),
            "updated_at": cell_str(r, 9)
        })).collect::<Vec<_>>(),
        "process_events": ev.rows.iter().map(|r| json!({
            "seq": cell_i64(r, 0).unwrap_or(0),
            "event_id": cell_str(r, 1),
            "process_id": cell_str(r, 2),
            "kind": cell_str(r, 3),
            "step_id": cell_str(r, 4),
            "attempt": cell_i64(r, 5).unwrap_or(1),
            "recorded_at": cell_str(r, 6),
            "payload": parse_json_cell(r, 7)
        })).collect::<Vec<_>>(),
        "blueprints": bp.rows.iter().map(|r| json!({
            "candidate_id": cell_str(r, 0),
            "intent": cell_str(r, 1),
            "schedule_class": cell_str(r, 2),
            "schedule_expression": cell_str(r, 3),
            "state": cell_str(r, 4),
            "enabled": cell_str(r, 5) == "t" || cell_str(r, 5) == "true",
            "shadow_only": cell_str(r, 6) == "t" || cell_str(r, 6) == "true",
            "confidence": cell_str(r, 7),
            "proposer": cell_str(r, 8),
            "resource_scope": cell_str(r, 9),
            "estimated_cost_microusd": cell_i64(r, 10).unwrap_or(0),
            "required_tools": parse_json_cell(r, 11),
            "isolation_profile": parse_json_cell(r, 12)
        })).collect::<Vec<_>>()
    })
}

pub async fn fetch_scheduler_runs(db: &DbHandle) -> Value {
    let task_sql = "SELECT task_id, name, COALESCE(schedule_kind, ''), COALESCE(cron_expression, ''), \
                    enabled, COALESCE(resource_ref, ''), \
                    COALESCE(to_char(last_run AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') \
                    FROM scheduled_task ORDER BY created_at DESC LIMIT 50";
    let run_sql = "SELECT run_id, task_id, status, attempt, COALESCE(error_kind, ''), \
                   to_char(scheduled_for AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
                   COALESCE(to_char(completed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') \
                   FROM schedule_dispatch_run ORDER BY scheduled_for DESC LIMIT 50";
    let snap_sql = "SELECT id, status, source, observation_kind, \
                    COALESCE(resource_count, 0), COALESCE(link_count, 0), \
                    COALESCE(failure_code, ''), \
                    to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
                    COALESCE(to_char(completed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') \
                    FROM inventory_snapshot ORDER BY started_at DESC LIMIT 20";
    let cost_sql = "SELECT run_id, package_id, scope_id, status, observation_count, \
                    COALESCE(failure_reason, ''), \
                    to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
                    COALESCE(to_char(finished_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') \
                    FROM cost_governance_analytics_run_receipt ORDER BY started_at DESC LIMIT 20";
    let (Ok(tasks), Ok(runs), Ok(snaps), Ok(costs)) = tokio::join!(
        db.query_single_readonly(task_sql),
        db.query_single_readonly(run_sql),
        db.query_single_readonly(snap_sql),
        db.query_single_readonly(cost_sql),
    ) else {
        return db.not_measured(
            "operations",
            "/api/v4/operations/scheduler-runs",
            "postgres_unreachable",
        );
    };

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "scheduled_tasks": tasks.rows.iter().map(|r| json!({
            "task_id": cell_str(r, 0),
            "name": cell_str(r, 1),
            "schedule_kind": cell_str(r, 2),
            "cron_expression": cell_str(r, 3),
            "enabled": cell_str(r, 4) == "t" || cell_str(r, 4) == "true",
            "resource_ref": cell_str(r, 5),
            "last_run": cell_str(r, 6)
        })).collect::<Vec<_>>(),
        "dispatch_runs": runs.rows.iter().map(|r| json!({
            "run_id": cell_str(r, 0),
            "task_id": cell_str(r, 1),
            "status": cell_str(r, 2),
            "attempt": cell_i64(r, 3).unwrap_or(1),
            "error_kind": cell_str(r, 4),
            "scheduled_for": cell_str(r, 5),
            "completed_at": cell_str(r, 6)
        })).collect::<Vec<_>>(),
        "inventory_runs": snaps.rows.iter().map(|r| json!({
            "id": cell_str(r, 0),
            "status": cell_str(r, 1),
            "source": cell_str(r, 2),
            "observation_kind": cell_str(r, 3),
            "resource_count": cell_i64(r, 4).unwrap_or(0),
            "link_count": cell_i64(r, 5).unwrap_or(0),
            "failure_code": cell_str(r, 6),
            "started_at": cell_str(r, 7),
            "completed_at": cell_str(r, 8)
        })).collect::<Vec<_>>(),
        "analytics_runs": costs.rows.iter().map(|r| json!({
            "run_id": cell_str(r, 0),
            "package_id": cell_str(r, 1),
            "scope_id": cell_str(r, 2),
            "status": cell_str(r, 3),
            "observation_count": cell_i64(r, 4).unwrap_or(0),
            "failure_reason": cell_str(r, 5),
            "started_at": cell_str(r, 6),
            "finished_at": cell_str(r, 7)
        })).collect::<Vec<_>>()
    })
}

pub async fn fetch_background_tasks(db: &DbHandle) -> Value {
    let proj_sql = "SELECT task_id, task_kind, status, COALESCE(request_summary, ''), \
                    COALESCE(accountable_agent, ''), COALESCE(result_summary, ''), \
                    to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                    FROM operator_background_task_projection ORDER BY updated_at DESC LIMIT 50";
    let prog_sql = "SELECT run_id, MAX(sequence)::bigint AS max_seq, \
                    (ARRAY_AGG(stage ORDER BY event_id DESC))[1] AS latest_stage, \
                    (ARRAY_AGG(state ORDER BY event_id DESC))[1] AS latest_state, \
                    to_char(MAX(recorded_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                    FROM inventory_progress_event \
                    GROUP BY run_id ORDER BY MAX(event_id) DESC LIMIT 20";
    let (Ok(proj), Ok(prog)) = tokio::join!(
        db.query_single_readonly(proj_sql),
        db.query_single_readonly(prog_sql),
    ) else {
        return db.not_measured(
            "operations",
            "/api/v4/operations/background-tasks",
            "postgres_unreachable",
        );
    };

    let operator_tasks: Vec<Value> = proj
        .rows
        .iter()
        .map(|r| {
            json!({
                "task_id": cell_str(r, 0),
                "task_kind": cell_str(r, 1),
                "status": cell_str(r, 2),
                "request_summary": cell_str(r, 3),
                "accountable_agent": cell_str(r, 4),
                "result_summary": cell_str(r, 5),
                "updated_at": cell_str(r, 6)
            })
        })
        .collect();

    let inventory_progress_runs: Vec<Value> = prog
        .rows
        .iter()
        .map(|r| {
            json!({
                "run_id": cell_str(r, 0),
                "steps": cell_i64(r, 1).unwrap_or(0),
                "stage": cell_str(r, 2),
                "state": cell_str(r, 3),
                "recorded_at": cell_str(r, 4)
            })
        })
        .collect();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "count": operator_tasks.len() + inventory_progress_runs.len(),
        "operator_tasks": operator_tasks,
        "inventory_progress_runs": inventory_progress_runs
    })
}

pub async fn fetch_scheduled_continuations(db: &DbHandle) -> Value {
    let anc_sql = "SELECT anchor_id, task_id, run_id, COALESCE(scope_ref, ''), mode, state, \
                   COALESCE(result_digest, ''), COALESCE(result_summary, ''), \
                   to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
                   COALESCE(to_char(expires_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') \
                   FROM scheduled_conversation_anchor ORDER BY created_at DESC LIMIT 50";
    let Ok(anc) = db.query_single_readonly(anc_sql).await else {
        return db.not_measured(
            "operations",
            "/api/v4/operations/scheduled-continuations",
            "postgres_unreachable",
        );
    };

    let items: Vec<Value> = anc
        .rows
        .iter()
        .map(|r| {
            json!({
                "anchor_id": cell_str(r, 0),
                "task_id": cell_str(r, 1),
                "run_id": cell_str(r, 2),
                "scope_ref": cell_str(r, 3),
                "mode": cell_str(r, 4),
                "state": cell_str(r, 5),
                "result_digest": cell_str(r, 6),
                "result_summary": cell_str(r, 7),
                "created_at": cell_str(r, 8),
                "expires_at": cell_str(r, 9)
            })
        })
        .collect();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "count": items.len(),
        "items": items
    })
}

pub async fn fetch_provision(db: &DbHandle) -> Value {
    let preflight_sql = "SELECT key, value::text, \
                         to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                         FROM state_kv WHERE key LIKE 'deploy-preflight:%' \
                         ORDER BY updated_at DESC LIMIT 10";
    let ready_sql = "SELECT value::text, \
                     to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                     FROM state_kv WHERE key = 'runtime:startup-readiness:latest' LIMIT 1";
    let lic_sql = "SELECT notice, \
                   to_char(observed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                   FROM licensing_entitlement_state LIMIT 1";
    let snap_sql = "SELECT id, status, source, COALESCE(resource_count, 0), COALESCE(link_count, 0), \
                    COALESCE(to_char(promoted_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') \
                    FROM inventory_snapshot ORDER BY started_at DESC LIMIT 5";
    let scope_sql = "SELECT value::text FROM state_kv WHERE key = 'operator-projection:operations:scope.effective' LIMIT 1";
    let prog_sql = "SELECT run_id, MAX(sequence)::bigint, \
                    (ARRAY_AGG(stage ORDER BY event_id DESC))[1], \
                    (ARRAY_AGG(state ORDER BY event_id DESC))[1], \
                    to_char(MAX(recorded_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                    FROM inventory_progress_event GROUP BY run_id ORDER BY MAX(event_id) DESC LIMIT 1";
    let (Ok(pf), Ok(rd), Ok(lic), Ok(snaps), scope_res, prog_res) = tokio::join!(
        db.query_single_readonly(preflight_sql),
        db.query_single_readonly(ready_sql),
        db.query_single_readonly(lic_sql),
        db.query_single_readonly(snap_sql),
        db.query_single_readonly(scope_sql),
        db.query_single_readonly(prog_sql),
    ) else {
        return db.not_measured("operations", "/api/v4/operations/provision", "postgres_unreachable");
    };

    let effective_scope = scope_res
        .ok()
        .and_then(|r| r.rows.first().map(|row| parse_json_cell(row, 0)))
        .unwrap_or(Value::Null);
    let latest_progress_run = prog_res
        .ok()
        .and_then(|r| {
            r.rows.first().map(|row| {
                json!({
                    "run_id": cell_str(row, 0),
                    "steps": cell_i64(row, 1).unwrap_or(0),
                    "stage": cell_str(row, 2),
                    "state": cell_str(row, 3),
                    "recorded_at": cell_str(row, 4)
                })
            })
        })
        .unwrap_or(Value::Null);

    let preflight: Vec<Value> = pf
        .rows
        .iter()
        .map(|r| {
            json!({
                "key": cell_str(r, 0),
                "payload": parse_json_cell(r, 1),
                "updated_at": cell_str(r, 2)
            })
        })
        .collect();

    let startup_readiness = rd
        .rows
        .first()
        .map(|r| json!({ "payload": parse_json_cell(r, 0), "updated_at": cell_str(r, 1) }))
        .unwrap_or(Value::Null);

    let entitlement = lic
        .rows
        .first()
        .map(|r| json!({ "notice": cell_str(r, 0), "observed_at": cell_str(r, 1) }))
        .unwrap_or(Value::Null);

    let snapshots: Vec<Value> = snaps
        .rows
        .iter()
        .map(|r| {
            json!({
                "id": cell_str(r, 0),
                "status": cell_str(r, 1),
                "source": cell_str(r, 2),
                "resource_count": cell_i64(r, 3).unwrap_or(0),
                "link_count": cell_i64(r, 4).unwrap_or(0),
                "promoted_at": cell_str(r, 5)
            })
        })
        .collect();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "effective_scope": effective_scope,
        "latest_progress_run": latest_progress_run,
        "preflight": preflight,
        "startup_readiness": startup_readiness,
        "entitlement": entitlement,
        "snapshots": snapshots
    })
}

pub async fn fetch_onboarding(db: &DbHandle) -> Value {
    let onb_sql = "SELECT value::text, \
                   to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                   FROM state_kv WHERE key = 'operator-projection:operations:onboarding' LIMIT 1";
    let scope_sql = "SELECT value::text FROM state_kv WHERE key = 'operator-projection:operations:scope.effective' LIMIT 1";
    let stew_sql = "SELECT value::text FROM state_kv WHERE key = 'operator-projection:operations:stewardship.coverage' LIMIT 1";
    let ready_sql = "SELECT value::text, \
                     to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                     FROM state_kv WHERE key = 'runtime:startup-readiness:latest' LIMIT 1";

    let (Ok(onb), Ok(scope), Ok(stew), Ok(ready)) = tokio::join!(
        db.query_single_readonly(onb_sql),
        db.query_single_readonly(scope_sql),
        db.query_single_readonly(stew_sql),
        db.query_single_readonly(ready_sql),
    ) else {
        return db.not_measured(
            "operations",
            "/api/v4/operations/onboarding",
            "postgres_unreachable",
        );
    };

    let onboarding = onb
        .rows
        .first()
        .map(|r| parse_json_cell(r, 0))
        .unwrap_or(Value::Null);
    let updated_at = onb
        .rows
        .first()
        .map(|r| cell_str(r, 1))
        .unwrap_or_default();
    let effective_scope = scope
        .rows
        .first()
        .map(|r| parse_json_cell(r, 0))
        .unwrap_or(Value::Null);
    let stewardship = stew
        .rows
        .first()
        .map(|r| parse_json_cell(r, 0))
        .unwrap_or(Value::Null);
    let readiness = ready
        .rows
        .first()
        .map(|r| {
            let mut m = Map::new();
            m.insert("payload".to_string(), parse_json_cell(r, 0));
            m.insert("updated_at".to_string(), json!(cell_str(r, 1)));
            Value::Object(m)
        })
        .unwrap_or(Value::Null);

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "onboarding": onboarding,
        "updated_at": updated_at,
        "effective_scope": effective_scope,
        "stewardship": stewardship,
        "startup_readiness": readiness
    })
}

