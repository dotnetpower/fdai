//! Domain 3 (`agents`, 6 panels) PostgreSQL repository.
//! Queries `audit_log`, `state_kv` projections (`stewardship.coverage`,
//! `capabilities`, `workflow.action-type-list`), and `workflow_definition`
//! with `pg_quote_literal` parameter escaping and honest `not-measured` fallbacks.

use crate::db::{cell_i64, cell_str, clamp_limit, DbHandle};
use fdai_adapter_postgres::pg_quote_literal;
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, BTreeSet};

const PANTHEON_NAMES: [&str; 15] = [
    "Odin",
    "Thor",
    "Forseti",
    "Huginn",
    "Heimdall",
    "Vidar",
    "Var",
    "Bragi",
    "Saga",
    "Mimir",
    "Muninn",
    "Norns",
    "Njord",
    "Freyr",
    "Loki",
];

/// Map a runtime `audit_log` `(actor, action_kind)` pair onto its owning
/// canonical 15-agent Pantheon member when deterministic attribution exists.
#[must_use]
pub fn attribute_pantheon_agent(actor: &str, action_kind: &str) -> Option<&'static str> {
    let trimmed_actor = actor.trim();
    if let Some(direct) = PANTHEON_NAMES
        .iter()
        .copied()
        .find(|name| name.eq_ignore_ascii_case(trimmed_actor))
    {
        return Some(direct);
    }

    let actor_low = trimmed_actor.to_ascii_lowercase();
    let kind_low = action_kind.trim().to_ascii_lowercase();

    match actor_low.as_str() {
        "fdai.core.control_loop" => Some("Forseti"),
        "fdai.measurement" | "fdai.delivery.observation_campaign" => Some("Heimdall"),
        "fdai.core.rca" => Some("Norns"),
        "fdai.core.hil_resume" | "fdai.core.hil_resume.load_control" => Some("Var"),
        "handover-readiness-observer" | "runtime.startup" => Some("Odin"),
        "fdai.system" => {
            if kind_low.starts_with("mimir.") {
                Some("Mimir")
            } else if kind_low.starts_with("decision-evidence.") {
                Some("Muninn")
            } else if kind_low.starts_with("observer.") {
                Some("Huginn")
            } else {
                Some("Odin")
            }
        }
        _ => None,
    }
}

/// Build a safe SQL predicate matching direct and attributed `audit_log` rows
/// for one canonical Pantheon agent using `pg_quote_literal`.
#[must_use]
pub fn build_agent_where_clause(agent_name: &str) -> String {
    let q_direct = pg_quote_literal(agent_name);
    match agent_name {
        "Forseti" => format!(
            "(lower(actor) = lower({q_direct}) OR actor = {})",
            pg_quote_literal("fdai.core.control_loop")
        ),
        "Heimdall" => format!(
            "(lower(actor) = lower({q_direct}) OR actor IN ({}, {}))",
            pg_quote_literal("fdai.measurement"),
            pg_quote_literal("fdai.delivery.observation_campaign")
        ),
        "Norns" => format!(
            "(lower(actor) = lower({q_direct}) OR actor = {})",
            pg_quote_literal("fdai.core.rca")
        ),
        "Var" => format!(
            "(lower(actor) = lower({q_direct}) OR actor IN ({}, {}))",
            pg_quote_literal("fdai.core.hil_resume"),
            pg_quote_literal("fdai.core.hil_resume.load_control")
        ),
        "Mimir" => format!(
            "(lower(actor) = lower({q_direct}) OR (actor = {} AND action_kind LIKE {}))",
            pg_quote_literal("fdai.system"),
            pg_quote_literal("mimir.%")
        ),
        "Muninn" => format!(
            "(lower(actor) = lower({q_direct}) OR (actor = {} AND action_kind LIKE {}))",
            pg_quote_literal("fdai.system"),
            pg_quote_literal("decision-evidence.%")
        ),
        "Huginn" => format!(
            "(lower(actor) = lower({q_direct}) OR (actor = {} AND action_kind LIKE {}))",
            pg_quote_literal("fdai.system"),
            pg_quote_literal("observer.%")
        ),
        "Odin" => format!(
            "(lower(actor) = lower({q_direct}) OR actor IN ({}, {}) OR (actor = {} AND action_kind LIKE {}))",
            pg_quote_literal("handover-readiness-observer"),
            pg_quote_literal("runtime.startup"),
            pg_quote_literal("fdai.system"),
            pg_quote_literal("startup_readiness.%")
        ),
        _ => format!("lower(actor) = lower({q_direct})"),
    }
}

#[derive(Default)]
struct AgentAgg {
    direct_count: i64,
    attributed_count: i64,
    last_seen_at: String,
    last_seen_epoch_ms: i64,
    latest_action_kind: String,
    modes: BTreeSet<String>,
    top_actions: Vec<(String, i64)>,
}

fn classify_agent_status(direct_count: i64, total_count: i64) -> &'static str {
    if total_count <= 0 {
        "idle"
    } else if direct_count > 0 || total_count >= 25 {
        "working"
    } else {
        "watching"
    }
}

fn activity_label_7d(total_count: i64) -> String {
    if total_count <= 0 {
        String::from("최근 7일 활동 0건 · 대기")
    } else {
        format!("최근 7일 활동 {total_count}건")
    }
}

pub async fn fetch_actor_summary(db: &DbHandle) -> Value {
    let totals_sql = "SELECT count(*), \
                      count(*) FILTER (WHERE mode = 'shadow'), \
                      count(*) FILTER (WHERE mode = 'enforce'), \
                      COALESCE(max(seq), 0), \
                      COALESCE(max(to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')), ''), \
                      count(*) FILTER (WHERE created_at >= now() - interval '7 days'), \
                      COALESCE(min(to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')), '') \
                      FROM audit_log";
    let actors_sql = "SELECT actor, action_kind, count(*), \
                      COALESCE(max(to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')), ''), \
                      COALESCE(string_agg(DISTINCT mode, ','), ''), \
                      COALESCE((EXTRACT(EPOCH FROM max(created_at)) * 1000)::bigint, 0) \
                      FROM audit_log \
                      GROUP BY actor, action_kind \
                      ORDER BY count(*) DESC \
                      LIMIT 80";

    let (Ok(totals_res), Ok(actors_res)) = (
        db.query_single_readonly(totals_sql).await,
        db.query_single_readonly(actors_sql).await,
    ) else {
        return db.not_measured("agents", "/api/v4/agents/summary", "postgres_unreachable");
    };

    let tr = totals_res.rows.first().map(Vec::as_slice).unwrap_or(&[]);
    let total_events = cell_i64(tr, 0).unwrap_or(0);
    let shadow_events = cell_i64(tr, 1).unwrap_or(0);
    let enforce_events = cell_i64(tr, 2).unwrap_or(0);
    let latest_seq = cell_i64(tr, 3).unwrap_or(0);
    let latest_audit_at = cell_str(tr, 4);
    let audit_7d_total = cell_i64(tr, 5).unwrap_or(0);
    let earliest_audit_at = cell_str(tr, 6);

    let mut pantheon_map: BTreeMap<&'static str, AgentAgg> = BTreeMap::new();
    for name in PANTHEON_NAMES {
        pantheon_map.insert(name, AgentAgg::default());
    }

    let mut raw_actor_totals: BTreeMap<String, (i64, String, BTreeSet<String>)> = BTreeMap::new();

    for row in &actors_res.rows {
        let actor = cell_str(row, 0);
        let action_kind = cell_str(row, 1);
        let count = cell_i64(row, 2).unwrap_or(0);
        let last_seen = cell_str(row, 3);
        let modes_csv = cell_str(row, 4);
        let last_seen_ms = cell_i64(row, 5).unwrap_or(0);

        let raw_entry = raw_actor_totals.entry(actor.clone()).or_insert_with(|| {
            (0_i64, String::new(), BTreeSet::new())
        });
        raw_entry.0 = raw_entry.0.saturating_add(count);
        if last_seen > raw_entry.1 {
            raw_entry.1 = last_seen.clone();
        }
        for m in modes_csv.split(',').map(str::trim).filter(|s| !s.is_empty()) {
            raw_entry.2.insert(m.to_string());
        }

        if let Some(canon) = attribute_pantheon_agent(&actor, &action_kind) {
            if let Some(agg) = pantheon_map.get_mut(canon) {
                if actor.eq_ignore_ascii_case(canon) {
                    agg.direct_count = agg.direct_count.saturating_add(count);
                } else {
                    agg.attributed_count = agg.attributed_count.saturating_add(count);
                }
                if last_seen > agg.last_seen_at {
                    agg.last_seen_at = last_seen.clone();
                    agg.last_seen_epoch_ms = last_seen_ms;
                    agg.latest_action_kind = action_kind.clone();
                } else if last_seen_ms > agg.last_seen_epoch_ms {
                    agg.last_seen_epoch_ms = last_seen_ms;
                }
                for m in modes_csv.split(',').map(str::trim).filter(|s| !s.is_empty()) {
                    agg.modes.insert(m.to_string());
                }
                if agg.top_actions.len() < 6 {
                    agg.top_actions.push((action_kind, count));
                }
            }
        }
    }

    let mut actors: Vec<Value> = raw_actor_totals
        .into_iter()
        .map(|(actor, (cnt, last_seen, modes))| {
            let modes_vec: Vec<String> = modes.into_iter().collect();
            json!({
                "actor": actor,
                "event_count": cnt,
                "last_seen_at": last_seen,
                "modes": modes_vec
            })
        })
        .collect();
    actors.sort_by(|a, b| {
        let ca = a["event_count"].as_i64().unwrap_or(0);
        let cb = b["event_count"].as_i64().unwrap_or(0);
        cb.cmp(&ca)
    });

    let mut pantheon_activity = Map::new();
    let mut working_count = 0_usize;
    let mut watching_count = 0_usize;
    let mut idle_count = 0_usize;
    let mut unobserved_count = 0_usize;

    for name in PANTHEON_NAMES {
        if let Some(agg) = pantheon_map.get(name) {
            let total = agg.direct_count.saturating_add(agg.attributed_count);
            let status = classify_agent_status(agg.direct_count, total);
            match status {
                "working" => working_count += 1,
                "watching" => watching_count += 1,
                "idle" => idle_count += 1,
                _ => unobserved_count += 1,
            }
            let modes_vec: Vec<String> = agg.modes.iter().cloned().collect();
            let top_actions: Vec<Value> = agg
                .top_actions
                .iter()
                .map(|(k, c)| json!({ "action_kind": k, "count": c }))
                .collect();
            pantheon_activity.insert(
                name.to_string(),
                json!({
                    "agent": name,
                    "observed": true,
                    "active_7d": total > 0,
                    "status": status,
                    "activity_label": activity_label_7d(total),
                    "event_count": total,
                    "direct_event_count": agg.direct_count,
                    "attributed_event_count": agg.attributed_count,
                    "last_seen_at": if agg.last_seen_at.is_empty() { Value::Null } else { json!(agg.last_seen_at) },
                    "last_seen_epoch_ms": if agg.last_seen_epoch_ms > 0 { json!(agg.last_seen_epoch_ms) } else { Value::Null },
                    "latest_action_kind": if agg.latest_action_kind.is_empty() { Value::Null } else { json!(agg.latest_action_kind) },
                    "modes": modes_vec,
                    "top_actions": top_actions
                }),
            );
        }
    }

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "window_days": 7,
        "audit_total": total_events,
        "audit_7d_total": audit_7d_total,
        "audit_shadow": shadow_events,
        "audit_enforce": enforce_events,
        "latest_seq": latest_seq,
        "earliest_audit_at": if earliest_audit_at.is_empty() { Value::Null } else { json!(earliest_audit_at) },
        "latest_audit_at": latest_audit_at,
        "status_counts": {
            "working": working_count,
            "watching": watching_count,
            "idle": idle_count,
            "unobserved": unobserved_count
        },
        "pantheon_activity": Value::Object(pantheon_activity),
        "actors": actors
    })
}

pub async fn fetch_agent_detail(
    db: &DbHandle,
    agent_name: &str,
    limit: Option<usize>,
) -> Value {
    let lim = clamp_limit(limit, 20, 100);
    let where_clause = build_agent_where_clause(agent_name);

    let count_sql = format!(
        "SELECT count(*), \
         COALESCE(max(to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')), ''), \
         COALESCE(string_agg(DISTINCT mode, ','), ''), \
         COALESCE((EXTRACT(EPOCH FROM max(created_at)) * 1000)::bigint, 0) \
         FROM audit_log WHERE {where_clause}"
    );
    let list_sql = format!(
        "SELECT seq, COALESCE(correlation_id, ''), actor, action_kind, mode, \
         COALESCE(entry_hash, ''), \
         COALESCE(entry->>'stage', ''), \
         COALESCE(entry->>'reason', ''), \
         COALESCE(entry->>'source', ''), \
         COALESCE(entry->>'tier', ''), \
         to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
         (EXTRACT(EPOCH FROM created_at) * 1000)::bigint \
         FROM audit_log WHERE {where_clause} \
         ORDER BY seq DESC LIMIT {lim}"
    );

    let (Ok(cnt_res), Ok(list_res)) = (
        db.query_single_readonly(&count_sql).await,
        db.query_single_readonly(&list_sql).await,
    ) else {
        return db.not_measured("agents", "/api/v4/agents/pantheon", "postgres_unreachable");
    };

    let cr = cnt_res.rows.first().map(Vec::as_slice).unwrap_or(&[]);
    let event_count = cell_i64(cr, 0).unwrap_or(0);
    let last_seen_at = cell_str(cr, 1);
    let modes_csv = cell_str(cr, 2);
    let last_seen_epoch_ms = cell_i64(cr, 3).unwrap_or(0);
    let modes: Vec<String> = modes_csv
        .split(',')
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .collect();

    let items: Vec<Value> = list_res
        .rows
        .iter()
        .map(|row| {
            json!({
                "seq": cell_i64(row, 0),
                "correlation_id": cell_str(row, 1),
                "actor": cell_str(row, 2),
                "canonical_agent": agent_name,
                "action_kind": cell_str(row, 3),
                "mode": cell_str(row, 4),
                "entry_hash": cell_str(row, 5),
                "stage": cell_str(row, 6),
                "reason": cell_str(row, 7),
                "source": cell_str(row, 8),
                "tier": cell_str(row, 9),
                "created_at": cell_str(row, 10),
                "created_at_ms": cell_i64(row, 11)
            })
        })
        .collect();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "window_days": 7,
        "agent": agent_name,
        "observed": true,
        "active_7d": event_count > 0,
        "status": classify_agent_status(0, event_count),
        "activity_label": activity_label_7d(event_count),
        "event_count": event_count,
        "last_seen_at": if last_seen_at.is_empty() { Value::Null } else { json!(last_seen_at) },
        "last_seen_epoch_ms": if last_seen_epoch_ms > 0 { json!(last_seen_epoch_ms) } else { Value::Null },
        "modes": modes,
        "items": items
    })
}

pub async fn fetch_handover_stewardship(db: &DbHandle) -> Value {
    let key = pg_quote_literal("operator-projection:operations:stewardship.coverage");
    let kv_sql = format!(
        "SELECT value::text, \
         COALESCE(to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') \
         FROM state_kv WHERE key = {key} LIMIT 1"
    );
    let obs_sql = format!(
        "SELECT seq, COALESCE(correlation_id, ''), actor, action_kind, mode, \
         COALESCE(entry_hash, ''), \
         to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
         FROM audit_log \
         WHERE action_kind = {} \
         ORDER BY seq DESC LIMIT 5",
        pg_quote_literal("handover.readiness.observed")
    );
    let obs_cnt_sql = format!(
        "SELECT count(*) FROM audit_log WHERE action_kind = {}",
        pg_quote_literal("handover.readiness.observed")
    );

    let Ok(kv_res) = db.query_single_readonly(&kv_sql).await else {
        return db.not_measured("agents", "/api/v4/agents/handover", "postgres_unreachable");
    };
    let Some(first_row) = kv_res.rows.first() else {
        return db.not_measured(
            "agents",
            "/api/v4/agents/handover",
            "stewardship_projection_not_found",
        );
    };
    let raw_json = cell_str(first_row, 0);
    let updated_at = cell_str(first_row, 1);
    let Ok(parsed) = serde_json::from_str::<Value>(&raw_json) else {
        return db.not_measured(
            "agents",
            "/api/v4/agents/handover",
            "stewardship_projection_invalid_json",
        );
    };

    let obs_count = db
        .query_single_readonly(&obs_cnt_sql)
        .await
        .ok()
        .and_then(|r| r.rows.first().and_then(|row| cell_i64(row, 0)))
        .unwrap_or(0);
    let readiness_observations: Vec<Value> = db
        .query_single_readonly(&obs_sql)
        .await
        .map(|res| {
            res.rows
                .iter()
                .map(|row| {
                    json!({
                        "seq": cell_i64(row, 0),
                        "correlation_id": cell_str(row, 1),
                        "actor": cell_str(row, 2),
                        "action_kind": cell_str(row, 3),
                        "mode": cell_str(row, 4),
                        "entry_hash": cell_str(row, 5),
                        "created_at": cell_str(row, 6)
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "projection_key": "operator-projection:operations:stewardship.coverage",
        "updated_at": updated_at,
        "revision": parsed.get("_revision").cloned().unwrap_or(Value::Null),
        "map": parsed.get("map").cloned().unwrap_or(Value::Null),
        "coverage": parsed.get("coverage").cloned().unwrap_or(Value::Null),
        "identity_health": parsed.get("identity_health").cloned().unwrap_or(Value::Null),
        "readiness_observation_count": obs_count,
        "readiness_observations": readiness_observations
    })
}

pub async fn fetch_activity(
    db: &DbHandle,
    agent: Option<&str>,
    correlation_id: Option<&str>,
    limit: Option<usize>,
) -> Value {
    let lim = clamp_limit(limit, 50, 200);
    let mut clauses: Vec<String> = Vec::new();
    if let Some(ag) = agent.map(str::trim).filter(|s| !s.is_empty()) {
        clauses.push(build_agent_where_clause(ag));
    }
    if let Some(cid) = correlation_id.map(str::trim).filter(|s| !s.is_empty()) {
        clauses.push(format!("correlation_id = {}", pg_quote_literal(cid)));
    }
    let where_sql = if clauses.is_empty() {
        String::new()
    } else {
        format!("WHERE {}", clauses.join(" AND "))
    };

    let list_sql = format!(
        "SELECT seq, COALESCE(correlation_id, ''), actor, action_kind, mode, \
         COALESCE(entry_hash, ''), \
         COALESCE(entry->>'stage', ''), \
         COALESCE(entry->>'reason', ''), \
         COALESCE(entry->>'source', ''), \
         COALESCE(entry->>'tier', ''), \
         COALESCE(entry->>'t1_outcome', ''), \
         COALESCE(entry->>'resource_id', COALESCE(entry->>'target', '')), \
         to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
         (EXTRACT(EPOCH FROM created_at) * 1000)::bigint \
         FROM audit_log {where_sql} \
         ORDER BY seq DESC LIMIT {lim}"
    );
    let total_sql = format!("SELECT count(*) FROM audit_log {where_sql}");
    let corr_sql = "SELECT correlation_id, count(*), \
                    max(to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')), \
                    max(seq) \
                    FROM audit_log \
                    WHERE correlation_id IS NOT NULL AND correlation_id <> '' \
                    GROUP BY correlation_id \
                    ORDER BY max(seq) DESC \
                    LIMIT 16";
    let heatmap_sql = format!(
        "SELECT EXTRACT(ISODOW FROM created_at AT TIME ZONE 'UTC')::int AS dow, \
         (EXTRACT(HOUR FROM created_at AT TIME ZONE 'UTC')::int / 2) AS slot, \
         count(*) \
         FROM audit_log \
         {where_sql} \
         GROUP BY 1, 2 \
         ORDER BY 1, 2"
    );
    let heatmap_buckets_sql = format!(
        "SELECT to_char(date_trunc('hour', created_at AT TIME ZONE 'UTC'), 'YYYY-MM-DD\"T\"HH24:00:00\"Z\"') AS bucket_utc, \
         count(*) \
         FROM audit_log \
         {where_sql} \
         GROUP BY 1 \
         ORDER BY 1 ASC \
         LIMIT 500"
    );

    let (Ok(list_res), Ok(total_res)) = (
        db.query_single_readonly(&list_sql).await,
        db.query_single_readonly(&total_sql).await,
    ) else {
        return db.not_measured("agents", "/api/v4/agents/activity", "postgres_unreachable");
    };

    let total_matching = total_res
        .rows
        .first()
        .and_then(|r| cell_i64(r, 0))
        .unwrap_or(0);

    let items: Vec<Value> = list_res
        .rows
        .iter()
        .map(|row| {
            let actor = cell_str(row, 2);
            let action_kind = cell_str(row, 3);
            let attributed_agent = attribute_pantheon_agent(&actor, &action_kind);
            let canonical_agent = attributed_agent.unwrap_or("Odin");
            json!({
                "seq": cell_i64(row, 0),
                "correlation_id": cell_str(row, 1),
                "actor": actor,
                "canonical_agent": canonical_agent,
                "attributed": attributed_agent.is_some(),
                "action_kind": action_kind,
                "mode": cell_str(row, 4),
                "entry_hash": cell_str(row, 5),
                "stage": cell_str(row, 6),
                "reason": cell_str(row, 7),
                "source": cell_str(row, 8),
                "tier": cell_str(row, 9),
                "outcome": cell_str(row, 10),
                "target": cell_str(row, 11),
                "created_at": cell_str(row, 12),
                "created_at_ms": cell_i64(row, 13)
            })
        })
        .collect();

    let correlations: Vec<Value> = db
        .query_single_readonly(corr_sql)
        .await
        .map(|res| {
            res.rows
                .iter()
                .map(|row| {
                    json!({
                        "correlation_id": cell_str(row, 0),
                        "event_count": cell_i64(row, 1).unwrap_or(0),
                        "last_seen_at": cell_str(row, 2),
                        "latest_seq": cell_i64(row, 3).unwrap_or(0)
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    let mut grid: [[i64; 12]; 7] = [[0; 12]; 7];
    if let Ok(hm_res) = db.query_single_readonly(&heatmap_sql).await {
        for row in &hm_res.rows {
            let dow = cell_i64(row, 0).unwrap_or(0);
            let slot = cell_i64(row, 1).unwrap_or(-1);
            let cnt = cell_i64(row, 2).unwrap_or(0);
            if (1..=7).contains(&dow) && (0..12).contains(&slot) {
                if let (Ok(di), Ok(si)) = (usize::try_from(dow - 1), usize::try_from(slot)) {
                    grid[di][si] = cnt;
                }
            }
        }
    }
    let heatmap_buckets: Vec<Value> = db
        .query_single_readonly(&heatmap_buckets_sql)
        .await
        .map(|res| {
            res.rows
                .iter()
                .map(|row| {
                    json!({
                        "bucket_utc": cell_str(row, 0),
                        "count": cell_i64(row, 1).unwrap_or(0)
                    })
                })
                .collect()
        })
        .unwrap_or_default();
    let mut active_slots = 0_usize;
    for row in &grid {
        for &v in row {
            if v > 0 {
                active_slots += 1;
            }
        }
    }
    let heatmap_rows: Vec<Vec<i64>> = grid.iter().map(|r| r.to_vec()).collect();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "window_days": 7,
        "total_matching": total_matching,
        "activity_label": activity_label_7d(total_matching),
        "returned": items.len(),
        "items": items,
        "correlations": correlations,
        "heatmap_active_slots": active_slots,
        "heatmap": heatmap_rows,
        "heatmap_buckets": heatmap_buckets
    })
}

pub async fn fetch_skills(db: &DbHandle) -> Value {
    let at_key = pg_quote_literal("operator-projection:workflow:workflow.action-type-list");
    let at_sql = format!(
        "SELECT value::text, \
         COALESCE(to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') \
         FROM state_kv WHERE key = {at_key} LIMIT 1"
    );
    let wf_sql = "SELECT definition_id, workflow_name, workflow_version, \
                  COALESCE(origin, ''), COALESCE(visibility, ''), COALESCE(lifecycle, ''), \
                  COALESCE(owner_ref, ''), COALESCE(definition_hash, ''), \
                  COALESCE(resolved_action_versions::text, '{}'), \
                  COALESCE(to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') \
                  FROM workflow_definition \
                  ORDER BY workflow_name ASC \
                  LIMIT 100";

    let (Ok(at_res), Ok(wf_res)) = (
        db.query_single_readonly(&at_sql).await,
        db.query_single_readonly(wf_sql).await,
    ) else {
        return db.not_measured("agents", "/api/v4/agents/skills", "postgres_unreachable");
    };

    let (action_types, action_types_revision, action_types_updated_at) =
        if let Some(row) = at_res.rows.first() {
            let raw = cell_str(row, 0);
            let updated = cell_str(row, 1);
            match serde_json::from_str::<Value>(&raw) {
                Ok(parsed) => {
                    let list = parsed
                        .get("action_types")
                        .and_then(Value::as_array)
                        .cloned()
                        .unwrap_or_default();
                    let rev = parsed.get("_revision").cloned().unwrap_or(Value::Null);
                    (list, rev, updated)
                }
                Err(_) => (Vec::new(), Value::Null, updated),
            }
        } else {
            (Vec::new(), Value::Null, String::new())
        };

    let workflows: Vec<Value> = wf_res
        .rows
        .iter()
        .map(|row| {
            let resolved_raw = cell_str(row, 8);
            let resolved_actions = serde_json::from_str::<Value>(&resolved_raw)
                .unwrap_or_else(|_| json!({}));
            json!({
                "definition_id": cell_str(row, 0),
                "workflow_name": cell_str(row, 1),
                "workflow_version": cell_str(row, 2),
                "origin": cell_str(row, 3),
                "visibility": cell_str(row, 4),
                "lifecycle": cell_str(row, 5),
                "owner_ref": cell_str(row, 6),
                "definition_hash": cell_str(row, 7),
                "resolved_action_versions": resolved_actions,
                "created_at": cell_str(row, 9),
                "read_only_boundary": true,
                "authority_escalation": "not_applicable"
            })
        })
        .collect();

    if action_types.is_empty() && workflows.is_empty() {
        return db.not_measured("agents", "/api/v4/agents/skills", "skills_catalog_empty");
    }

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "read_only_boundary": true,
        "authority_escalation": "not_applicable",
        "grants_execution_authority": false,
        "workflow_count": workflows.len(),
        "action_type_count": action_types.len(),
        "action_types_revision": action_types_revision,
        "action_types_updated_at": action_types_updated_at,
        "workflows": workflows,
        "action_types": action_types
    })
}

pub async fn fetch_capabilities(db: &DbHandle) -> Value {
    let key = pg_quote_literal("operator-projection:operations:capabilities");
    let sql = format!(
        "SELECT value::text, \
         COALESCE(to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') \
         FROM state_kv WHERE key = {key} LIMIT 1"
    );

    let Ok(res) = db.query_single_readonly(&sql).await else {
        return db.not_measured("agents", "/api/v4/agents/capabilities", "postgres_unreachable");
    };
    let Some(row) = res.rows.first() else {
        return db.not_measured(
            "agents",
            "/api/v4/agents/capabilities",
            "capabilities_projection_not_found",
        );
    };
    let raw = cell_str(row, 0);
    let updated_at = cell_str(row, 1);
    let Ok(parsed) = serde_json::from_str::<Value>(&raw) else {
        return db.not_measured(
            "agents",
            "/api/v4/agents/capabilities",
            "capabilities_projection_invalid_json",
        );
    };

    let caps = parsed
        .get("capabilities")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let mut category_counts: BTreeMap<String, usize> = BTreeMap::new();
    let mut mutating_count = 0_usize;
    for cap in &caps {
        let cat = cap
            .get("category")
            .and_then(Value::as_str)
            .unwrap_or("other")
            .to_string();
        let entry = category_counts.entry(cat).or_insert(0);
        *entry += 1;
        let side_effect = cap
            .get("side_effect_class")
            .and_then(Value::as_str)
            .unwrap_or("read");
        if side_effect != "read" {
            mutating_count += 1;
        }
    }

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "projection_key": "operator-projection:operations:capabilities",
        "updated_at": updated_at,
        "catalog_source": parsed.get("source").cloned().unwrap_or_else(|| json!("default-capability-catalog")),
        "revision": parsed.get("_revision").cloned().unwrap_or(Value::Null),
        "count": caps.len(),
        "mutating_count": mutating_count,
        "execution_eligibility": false,
        "grants_execution_authority": false,
        "category_counts": category_counts,
        "capabilities": caps
    })
}

pub async fn fetch_stream_snapshot(db: &DbHandle) -> Value {
    let summary_sql = "SELECT count(*), COALESCE(max(seq), 0), \
                       COALESCE(max(to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')), '') \
                       FROM audit_log";
    let recent_sql = "SELECT seq, COALESCE(correlation_id, ''), actor, action_kind, mode, \
                      to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
                      (EXTRACT(EPOCH FROM created_at) * 1000)::bigint \
                      FROM audit_log ORDER BY seq DESC LIMIT 8";

    let (Ok(sum_res), Ok(rec_res)) = (
        db.query_single_readonly(summary_sql).await,
        db.query_single_readonly(recent_sql).await,
    ) else {
        return db.not_measured("agents", "/api/v4/agents/stream", "postgres_unreachable");
    };

    let sr = sum_res.rows.first().map(Vec::as_slice).unwrap_or(&[]);
    let total_events = cell_i64(sr, 0).unwrap_or(0);
    let latest_seq = cell_i64(sr, 1).unwrap_or(0);
    let latest_audit_at = cell_str(sr, 2);

    let mut active_agents: BTreeSet<&'static str> = BTreeSet::new();
    let recent: Vec<Value> = rec_res
        .rows
        .iter()
        .map(|row| {
            let actor = cell_str(row, 2);
            let action_kind = cell_str(row, 3);
            let canonical_agent = attribute_pantheon_agent(&actor, &action_kind).unwrap_or("Odin");
            active_agents.insert(canonical_agent);
            json!({
                "seq": cell_i64(row, 0),
                "correlation_id": cell_str(row, 1),
                "actor": actor,
                "canonical_agent": canonical_agent,
                "action_kind": action_kind,
                "mode": cell_str(row, 4),
                "created_at": cell_str(row, 5),
                "created_at_ms": cell_i64(row, 6)
            })
        })
        .collect();

    let active_list: Vec<&str> = active_agents.into_iter().collect();

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "audit_total": total_events,
        "latest_seq": latest_seq,
        "latest_audit_at": latest_audit_at,
        "active_agents_recent": active_list,
        "recent": recent
    })
}

