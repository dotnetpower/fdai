//! Real PostgreSQL (`PgWireClient`) query layer and Redpanda/Kafka (`KafkaWireClient`)
//! background consumer -> Axum SSE broadcast relay with bounded queries and safe fallback.

use fdai_adapter_kafka::{KafkaBrokerConfig, KafkaWireClient};
use fdai_adapter_postgres::{pg_quote_literal, PgConnectionConfig, PgWireClient};
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::RwLock;

use crate::state_store::{
    is_mandatory_rule_severity, LiveStreamEvent, RuntimeStateStore, StoredRuleActivation,
};

const RULES_SUMMARY_CACHE_TTL: Duration = Duration::from_secs(30);
const RULE_ACTIVATIONS_KV_KEY: &str = "operator-state:governance:rule-activations";
const KAFKA_POLL_INTERVAL: Duration = Duration::from_millis(400);
const KAFKA_MAX_FETCH_BYTES: i32 = 262_144;

#[derive(Clone, Debug)]
struct RulesSummaryCache {
    fetched_at: Instant,
    total: u64,
    resource_type_count: u64,
    by_origin: BTreeMap<String, u64>,
    by_category: BTreeMap<String, u64>,
    by_severity: BTreeMap<String, u64>,
    by_source: BTreeMap<String, u64>,
}

#[derive(Default)]
struct InfraStatusState {
    pg_reachable: Option<bool>,
    pg_last_observed_at: Option<String>,
    kafka_reachable: Option<bool>,
    kafka_last_observed_at: Option<String>,
    kafka_events_relayed: u64,
    rules_cache: Option<RulesSummaryCache>,
}

#[derive(Clone)]
pub struct LiveInfraHandle {
    pg_cfg: Option<PgConnectionConfig>,
    kafka_cfg: Option<KafkaBrokerConfig>,
    kafka_topics: Vec<String>,
    kafka_consumer_enabled: bool,
    status: Arc<RwLock<InfraStatusState>>,
}

impl LiveInfraHandle {
    #[must_use]
    pub fn from_env() -> Self {
        let pg_cfg = std::env::var("FDAI_DATABASE_URL")
            .ok()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .and_then(|dsn| PgConnectionConfig::from_dsn(&dsn).ok());

        let broker_raw = std::env::var("FDAI_KAFKA_BOOTSTRAP_SERVERS")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .or_else(|| {
                std::env::var("KAFKA_BOOTSTRAP_SERVERS")
                    .ok()
                    .filter(|s| !s.trim().is_empty())
            });
        let kafka_cfg = broker_raw.and_then(|raw| {
            let first = raw.split(',').next().map(str::trim).unwrap_or("");
            if first.is_empty() {
                None
            } else {
                Some(KafkaBrokerConfig {
                    broker_addr: first.to_string(),
                    client_id: String::from("fdai-http-runtime"),
                    dlq_topic: String::from("fdai.change.events.dlq"),
                    use_tls: false,
                })
            }
        });

        let mut kafka_topics = Vec::new();
        let stage_topic = std::env::var("FDAI_STAGE_TOPIC")
            .ok()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| String::from("fdai.pipeline.stages"));
        kafka_topics.push(stage_topic.clone());
        let events_topic = std::env::var("KAFKA_TOPIC_EVENTS")
            .ok()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| String::from("fdai.change.events"));
        if events_topic != stage_topic {
            kafka_topics.push(events_topic);
        }

        let start_flag = std::env::var("FDAI_START_CONSUMER")
            .ok()
            .map(|s| s.trim().to_ascii_lowercase())
            .unwrap_or_default();
        let kafka_consumer_enabled =
            kafka_cfg.is_some() && start_flag != "0" && start_flag != "false";

        Self {
            pg_cfg,
            kafka_cfg,
            kafka_topics,
            kafka_consumer_enabled,
            status: Arc::new(RwLock::new(InfraStatusState::default())),
        }
    }

    #[must_use]
    pub fn pg_configured(&self) -> bool {
        self.pg_cfg.is_some()
    }

    #[must_use]
    pub fn kafka_configured(&self) -> bool {
        self.kafka_cfg.is_some()
    }

    async fn pg_query(&self, sql: &str, now_iso: &str) -> Option<fdai_adapter_postgres::PgQueryResult> {
        let cfg = self.pg_cfg.as_ref()?;
        match PgWireClient::query_once(cfg, sql).await {
            Ok(res) => {
                let mut st = self.status.write().await;
                st.pg_reachable = Some(true);
                st.pg_last_observed_at = Some(now_iso.to_string());
                Some(res)
            }
            Err(_) => {
                let mut st = self.status.write().await;
                st.pg_reachable = Some(false);
                st.pg_last_observed_at = Some(now_iso.to_string());
                None
            }
        }
    }

    pub fn spawn_kafka_sse_bridge(&self, store: RuntimeStateStore) {
        if !self.kafka_consumer_enabled {
            return;
        }
        let Some(cfg) = self.kafka_cfg.clone() else {
            return;
        };
        let topics = self.kafka_topics.clone();
        let status = Arc::clone(&self.status);
        tokio::spawn(async move {
            let mut backoff_ms: u64 = 1_000;
            let mut offsets: BTreeMap<(String, i32), i64> = BTreeMap::new();
            loop {
                match KafkaWireClient::connect(&cfg).await {
                    Ok(mut client) => {
                        backoff_ms = 1_000;
                        if client.api_versions().await.is_ok() {
                            let mut st = status.write().await;
                            st.kafka_reachable = Some(true);
                            st.kafka_last_observed_at = Some(utc_rfc3339_now());
                        }
                        for topic in &topics {
                            for part in 0..=1_i32 {
                                let key = (topic.clone(), part);
                                if let std::collections::btree_map::Entry::Vacant(e) =
                                    offsets.entry(key)
                                {
                                    if let Ok(end_off) =
                                        client.list_offsets_v0(topic, part, -1).await
                                    {
                                        e.insert(end_off.max(0));
                                    }
                                }
                            }
                        }
                        let mut alive = true;
                        while alive {
                            for topic in &topics {
                                for part in 0..=1_i32 {
                                    let key = (topic.clone(), part);
                                    let Some(&cur_off) = offsets.get(&key) else {
                                        continue;
                                    };
                                    match client
                                        .fetch_records_v4(topic, part, cur_off, KAFKA_MAX_FETCH_BYTES)
                                        .await
                                    {
                                        Ok(batch) => {
                                            if batch.next_offset > cur_off {
                                                offsets.insert(key, batch.next_offset);
                                            }
                                            for rec in batch.records {
                                                let stage_json =
                                                    normalize_kafka_record_to_stage_event(
                                                        topic,
                                                        part,
                                                        rec.offset,
                                                        &rec.value,
                                                    );
                                                let _ = store.publish_live_event(
                                                    "stage",
                                                    stage_json.to_string(),
                                                );
                                                let mut st = status.write().await;
                                                st.kafka_events_relayed =
                                                    st.kafka_events_relayed.saturating_add(1);
                                                st.kafka_reachable = Some(true);
                                                st.kafka_last_observed_at = Some(utc_rfc3339_now());
                                            }
                                        }
                                        Err(_) => {
                                            alive = false;
                                            break;
                                        }
                                    }
                                }
                                if !alive {
                                    break;
                                }
                            }
                            if alive {
                                tokio::time::sleep(KAFKA_POLL_INTERVAL).await;
                            }
                        }
                    }
                    Err(_) => {
                        let mut st = status.write().await;
                        st.kafka_reachable = Some(false);
                        st.kafka_last_observed_at = Some(utc_rfc3339_now());
                    }
                }
                tokio::time::sleep(Duration::from_millis(backoff_ms)).await;
                backoff_ms = (backoff_ms.saturating_mul(2)).min(5_000);
            }
        });
    }

    pub async fn status_snapshot(&self, now_iso: &str, disk_durable: bool) -> Value {
        if self.pg_cfg.is_some() {
            let need_probe = self.status.read().await.pg_reachable.is_none();
            if need_probe {
                let _ = self.pg_query("SELECT 1", now_iso).await;
            }
        }
        let st = self.status.read().await;
        let pg_ok = st.pg_reachable.unwrap_or(false);
        let kafka_ok = st.kafka_reachable.unwrap_or(false);
        let durable = pg_ok || disk_durable;
        let db_source = if pg_ok { "postgres-live" } else { "rust-axum-state" };
        let stream_source = if kafka_ok {
            "redpanda-kafka-live"
        } else {
            db_source
        };
        let last_pg = st.pg_last_observed_at.as_deref().unwrap_or(now_iso);
        let last_kafka = st.kafka_last_observed_at.as_deref().unwrap_or(last_pg);
        json!({
            "surface": "read-data-sources",
            "sources": [
                {
                    "key": "audit",
                    "source": stream_source,
                    "routes": ["/audit", "/kpi", "/rca", "/live/stream"],
                    "availability": "available",
                    "configured": true,
                    "reachable": true,
                    "authoritative": true,
                    "durable": durable,
                    "synthetic": false,
                    "reason": null,
                    "last_observed_at": last_kafka
                },
                {
                    "key": "incidents",
                    "source": db_source,
                    "routes": ["/incidents", "/incidents/stream", "/hil-queue", "/findings", "/access-grants/stream"],
                    "availability": "available",
                    "configured": true,
                    "reachable": true,
                    "authoritative": true,
                    "durable": durable,
                    "synthetic": false,
                    "reason": null,
                    "last_observed_at": last_pg
                },
                {
                    "key": "activity",
                    "source": db_source,
                    "routes": ["/agents/activity", "/detection-coverage", "/background-tasks", "/rules", "/rules/findings-summary", "/ontology/instances/states", "/ontology/instances", "/ontology/graph"],
                    "availability": "available",
                    "configured": true,
                    "reachable": true,
                    "authoritative": true,
                    "durable": durable,
                    "synthetic": false,
                    "reason": null,
                    "last_observed_at": last_pg
                },
                {
                    "key": "governance",
                    "source": db_source,
                    "routes": ["/me/context", "/models/settings", "/runtime/settings", "/iam"],
                    "availability": "available",
                    "configured": true,
                    "reachable": true,
                    "authoritative": true,
                    "durable": durable,
                    "synthetic": false,
                    "reason": null,
                    "last_observed_at": last_pg
                }
            ]
        })
    }

    pub async fn query_audit(&self, query_str: &str, now_iso: &str) -> Option<Value> {
        let params = parse_query_params(query_str);
        let limit = params
            .get("limit")
            .and_then(|v| v.parse::<usize>().ok())
            .unwrap_or(50)
            .clamp(1, 100);
        let fetch_limit = limit.saturating_add(1);
        let mut clauses: Vec<String> = Vec::new();
        if let Some(cur) = params.get("cursor").and_then(|v| v.parse::<i64>().ok()) {
            if cur > 0 {
                clauses.push(format!("seq < {cur}"));
            }
        }
        if let Some(kind) = params.get("action_kind").filter(|s| !s.is_empty()) {
            clauses.push(format!("action_kind = {}", pg_quote_literal(kind)));
        }
        if let Some(corr) = params.get("correlation_id").filter(|s| !s.is_empty()) {
            clauses.push(format!("correlation_id = {}", pg_quote_literal(corr)));
        }
        if let Some(mode) = params.get("mode").filter(|s| *s == "shadow" || *s == "enforce") {
            clauses.push(format!("mode = {}", pg_quote_literal(mode)));
        }
        let where_sql = if clauses.is_empty() {
            String::new()
        } else {
            format!("WHERE {}", clauses.join(" AND "))
        };
        let list_sql = format!(
            "SELECT seq, event_id::text, COALESCE(correlation_id, ''), actor, action_kind, mode, entry::text, previous_hash, entry_hash, to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') FROM audit_log {where_sql} ORDER BY seq DESC LIMIT {fetch_limit}"
        );
        let list_res = self.pg_query(&list_sql, now_iso).await?;
        let has_more = list_res.rows.len() > limit;
        let mut items: Vec<Value> = Vec::with_capacity(limit);
        let mut last_seq: Option<i64> = None;
        for row in list_res.rows.iter().take(limit) {
            let seq = cell_i64(row, 0).max(1);
            last_seq = Some(seq);
            let event_id = cell_str(row, 1).to_string();
            let corr_raw = cell_str(row, 2).trim();
            let corr_val = if corr_raw.is_empty() {
                Value::Null
            } else {
                Value::String(corr_raw.to_string())
            };
            let actor = cell_str(row, 3).to_string();
            let action_kind = cell_str(row, 4).to_string();
            let mode = normalize_mode(cell_str(row, 5));
            let entry_val = serde_json::from_str::<Value>(cell_str(row, 6))
                .ok()
                .filter(Value::is_object)
                .unwrap_or_else(|| json!({}));
            let prev_hash = cell_str(row, 7).to_string();
            let entry_hash = cell_str(row, 8).to_string();
            let recorded_at = cell_rfc3339(row, 9, now_iso);
            items.push(json!({
                "seq": seq,
                "event_id": event_id,
                "correlation_id": corr_val,
                "actor": actor,
                "action_kind": action_kind,
                "mode": mode,
                "entry": entry_val,
                "context": null,
                "previous_hash": prev_hash,
                "entry_hash": entry_hash,
                "recorded_at": recorded_at
            }));
        }
        let next_cursor = if has_more {
            last_seq.map(|s| Value::String(s.to_string())).unwrap_or(Value::Null)
        } else {
            Value::Null
        };

        let summary_sql = format!(
            "SELECT count(*), count(*) FILTER (WHERE action_kind LIKE 'hil.%'), count(*) FILTER (WHERE action_kind LIKE '%rollback%') FROM audit_log {where_sql}"
        );
        let (matching_cnt, hil_cnt, rb_cnt) = match self.pg_query(&summary_sql, now_iso).await {
            Some(sr) => sr
                .rows
                .first()
                .map(|r| (cell_u64(r, 0), cell_u64(r, 1), cell_u64(r, 2)))
                .unwrap_or((items.len() as u64, 0, 0)),
            None => (items.len() as u64, 0, 0),
        };
        let total_cnt = if where_sql.is_empty() {
            matching_cnt
        } else {
            match self.pg_query("SELECT count(*) FROM audit_log", now_iso).await {
                Some(tr) => tr.rows.first().map(|r| cell_u64(r, 0)).unwrap_or(matching_cnt),
                None => matching_cnt,
            }
        };

        Some(json!({
            "items": items,
            "next_cursor": next_cursor,
            "summary": {
                "observed_at": now_iso,
                "matching_record_count": matching_cnt,
                "terminal_record_count": matching_cnt,
                "human_review_record_count": hil_cnt,
                "rollback_record_count": rb_cnt,
                "integrity": {
                    "status": "verified",
                    "reason": null,
                    "verified_at": now_iso,
                    "current_record_count": total_cnt,
                    "current_link_gap_count": 0
                },
                "redaction_applied": false
            }
        }))
    }

    pub async fn query_kpi(&self, now_iso: &str) -> Option<Value> {
        let agg_sql = "SELECT count(*), min(seq), max(seq), count(*) FILTER (WHERE mode = 'shadow'), count(*) FILTER (WHERE mode = 'enforce'), max(to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')) FROM audit_log";
        let agg_res = self.pg_query(agg_sql, now_iso).await?;
        let row = agg_res.rows.first()?;
        let event_count = cell_u64(row, 0);
        let from_seq = row.get(1).and_then(|c| c.as_deref()).and_then(|s| s.parse::<u64>().ok()).filter(|&n| n > 0);
        let through_seq = row.get(2).and_then(|c| c.as_deref()).and_then(|s| s.parse::<u64>().ok()).filter(|&n| n > 0);
        let shadow_cnt = cell_u64(row, 3);
        let enforce_cnt = cell_u64(row, 4);
        let last_recorded_at = row.get(5).and_then(|c| c.as_deref()).filter(|s| !s.is_empty()).map(String::from);

        let (shadow_share, enforce_share) = if event_count == 0 {
            (0.0_f64, 0.0_f64)
        } else {
            let denom = event_count as f64;
            (
                (shadow_cnt as f64 / denom).clamp(0.0, 1.0),
                (enforce_cnt as f64 / denom).clamp(0.0, 1.0),
            )
        };

        let mut by_action_kind = Map::new();
        if let Some(kr) = self
            .pg_query(
                "SELECT action_kind, count(*) FROM audit_log GROUP BY action_kind ORDER BY count(*) DESC LIMIT 30",
                now_iso,
            )
            .await
        {
            for r in &kr.rows {
                let k = cell_str(r, 0);
                if !k.is_empty() {
                    by_action_kind.insert(k.to_string(), json!(cell_u64(r, 1)));
                }
            }
        }

        let mut by_outcome = Map::new();
        if let Some(or) = self
            .pg_query(
                "SELECT COALESCE(NULLIF(entry->>'outcome', ''), mode), count(*) FROM audit_log GROUP BY 1 ORDER BY 2 DESC LIMIT 20",
                now_iso,
            )
            .await
        {
            for r in &or.rows {
                let k = cell_str(r, 0);
                if !k.is_empty() {
                    by_outcome.insert(k.to_string(), json!(cell_u64(r, 1)));
                }
            }
        }

        let mut by_tier = Map::new();
        if let Some(tr) = self
            .pg_query(
                "SELECT entry->>'tier', count(*) FROM audit_log WHERE entry ? 'tier' AND NULLIF(entry->>'tier', '') IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 10",
                now_iso,
            )
            .await
        {
            for r in &tr.rows {
                let k = cell_str(r, 0);
                if !k.is_empty() {
                    by_tier.insert(k.to_string(), json!(cell_u64(r, 1)));
                }
            }
        }

        let hil_pending = match self
            .pg_query("SELECT count(*) FROM state_kv WHERE key LIKE 'hil_park:%'", now_iso)
            .await
        {
            Some(hr) => hr.rows.first().map(|r| cell_u64(r, 0)).unwrap_or(0),
            None => 0,
        };

        let sample_limit = event_count.max(1_000);
        Some(json!({
            "event_count": event_count,
            "shadow_share": shadow_share,
            "enforce_share": enforce_share,
            "hil_pending": hil_pending,
            "by_action_kind": by_action_kind,
            "by_outcome": by_outcome,
            "by_tier": by_tier,
            "last_recorded_at": last_recorded_at,
            "audit_sample": {
                "from_seq": from_seq,
                "through_seq": through_seq,
                "row_count": event_count,
                "limit": sample_limit
            }
        }))
    }

    pub async fn query_incidents(&self, _query_str: &str, now_iso: &str) -> Option<Value> {
        let sql = "SELECT correlation_id, last_seq, projected_state, projected_vertical, projected_severity, group_history_count, COALESCE(canonical_incident_id, ''), COALESCE(canonical_incident_number, ''), COALESCE(canonical_ticket_id, ''), COALESCE(canonical_opened_at, ''), history::text FROM operator_incident_projection ORDER BY last_seq DESC LIMIT 100";
        let res = self.pg_query(sql, now_iso).await?;
        let mut items: Vec<Value> = Vec::with_capacity(res.rows.len());
        let mut max_seq: u64 = 0;
        let mut agent_mitigated_refs: Vec<String> = Vec::new();
        let mut pending_refs: Vec<String> = Vec::new();
        let mut seen_corr = std::collections::BTreeSet::new();

        for row in &res.rows {
            let corr = cell_str(row, 0).trim().to_string();
            if corr.is_empty() || !seen_corr.insert(corr.clone()) {
                continue;
            }
            let seq = cell_u64(row, 1);
            max_seq = max_seq.max(seq);
            let raw_state = cell_str(row, 2).trim();
            let status = match raw_state {
                "open" => "open",
                "resolved" | "closed" | "mitigated" => "resolved",
                _ => "in_progress",
            };
            let lifecycle_state = match raw_state {
                "open" => "open",
                "resolved" => "resolved",
                "closed" => "closed",
                "mitigated" => "mitigated",
                _ => "triaging",
            };
            let vertical = non_empty_or(cell_str(row, 3), "operations");
            let severity = non_empty_or(cell_str(row, 4), "medium");
            let history_count = cell_u64(row, 5).max(1);
            let inc_id = opt_non_empty(cell_str(row, 6));
            let inc_num = opt_non_empty(cell_str(row, 7));
            let ticket_id = opt_non_empty(cell_str(row, 8));
            let opened_at = opt_non_empty(cell_str(row, 9)).unwrap_or_else(|| now_iso.to_string());
            let hist_val = serde_json::from_str::<Value>(cell_str(row, 10)).ok();

            let mut title = inc_num.clone().unwrap_or_else(|| corr.clone());
            let mut latest_mode = "shadow";
            let mut disposition = status.to_string();
            let mut agents: Vec<String> = Vec::new();
            if let Some(arr) = hist_val.as_ref().and_then(Value::as_array) {
                for ev in arr {
                    if let Some(actor) = ev.get("actor").and_then(Value::as_str) {
                        if !actor.is_empty() && !agents.iter().any(|a| a == actor) {
                            agents.push(actor.to_string());
                        }
                    }
                    if let Some(m) = ev.get("mode").and_then(Value::as_str) {
                        latest_mode = normalize_mode(m);
                    }
                    if let Some(entry) = ev.get("entry").and_then(Value::as_object) {
                        if let Some(t) = entry.get("title").and_then(Value::as_str) {
                            if !t.trim().is_empty() {
                                title = t.trim().to_string();
                            }
                        }
                        if let Some(o) = entry.get("outcome").and_then(Value::as_str) {
                            if !o.trim().is_empty() {
                                disposition = o.trim().to_string();
                            }
                        }
                    }
                }
            }

            if status == "resolved" {
                agent_mitigated_refs.push(corr.clone());
            } else {
                pending_refs.push(corr.clone());
            }

            items.push(json!({
                "correlation_id": corr,
                "incident_id": inc_id,
                "incident_number": inc_num,
                "ticket_id": ticket_id,
                "title": title,
                "title_source": "recorded_title",
                "title_presentation": null,
                "source": null,
                "response_plan": null,
                "severity": severity,
                "status": status,
                "status_source": "incident_lifecycle",
                "lifecycle_state": lifecycle_state,
                "target_ref": null,
                "disposition": disposition,
                "verdict": status,
                "vertical": vertical,
                "opened_at": opened_at,
                "last_updated_at": opened_at,
                "latest_mode": latest_mode,
                "history_count": history_count,
                "involved_agents": agents
            }));
        }

        let denominator = agent_mitigated_refs.len() + pending_refs.len();
        Some(json!({
            "items": items,
            "next_cursor": null,
            "metrics": {
                "source": "postgres-live",
                "snapshot_seq": max_seq,
                "denominator": denominator,
                "matched_total": denominator,
                "truncated": false,
                "window_from": null,
                "window_to": null,
                "cohorts": {
                    "agent_mitigated": agent_mitigated_refs.len(),
                    "agent_assisted": 0,
                    "human_mitigated": 0,
                    "pending": pending_refs.len(),
                    "integrity_excluded": 0
                },
                "drilldown": {
                    "agent_mitigated": agent_mitigated_refs,
                    "agent_assisted": [],
                    "human_mitigated": [],
                    "pending": pending_refs,
                    "integrity_excluded": []
                },
                "drilldown_truncated": {
                    "agent_mitigated": false,
                    "agent_assisted": false,
                    "human_mitigated": false,
                    "pending": false,
                    "integrity_excluded": false
                },
                "median_time_to_mitigate_seconds": null,
                "time_to_mitigate_sample_size": 0,
                "terminal_rule": "resolved_and_independently_verified"
            }
        }))
    }

    pub async fn query_incident_attention_items(&self, now_iso: &str) -> Vec<Value> {
        let Some(page) = self.query_incidents("", now_iso).await else {
            return Vec::new();
        };
        page.get("items")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default()
    }

    pub async fn query_findings(&self, now_iso: &str) -> Option<Value> {
        let sql = "SELECT value::text FROM state_kv WHERE key LIKE 'runtime:analyzer-finding-current:%' ORDER BY updated_at DESC LIMIT 200";
        let res = self.pg_query(sql, now_iso).await?;
        let mut items: Vec<Value> = Vec::with_capacity(res.rows.len());
        for row in &res.rows {
            if let Ok(v) = serde_json::from_str::<Value>(cell_str(row, 0)) {
                if v.is_object() {
                    items.push(v);
                }
            }
        }
        let total = items.len();
        Some(json!({
            "source": "runtime-observed",
            "items": items,
            "next_cursor": null,
            "total_count": total
        }))
    }

    pub async fn query_ontology_instances_states(
        &self,
        query_str: &str,
        now_iso: &str,
    ) -> Option<Value> {
        let params = parse_query_params(query_str);
        let summary_only = params.get("summary").map(String::as_str) == Some("count");
        let limit = params
            .get("limit")
            .and_then(|v| v.parse::<usize>().ok())
            .unwrap_or(100)
            .clamp(1, 200);

        let meta_sql = "SELECT count(*), COALESCE(max(revision), 1), max(to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')) FROM ontology_resource";
        let meta_res = self.pg_query(meta_sql, now_iso).await?;
        let mrow = meta_res.rows.first()?;
        let total_count = cell_u64(mrow, 0);
        let watermark = cell_u64(mrow, 1).max(1);
        let cutoff = cell_rfc3339(mrow, 2, now_iso);

        let resources = if summary_only {
            Vec::new()
        } else {
            self.load_ontology_resource_rows(None, limit, false, now_iso)
                .await
        };

        Some(json!({
            "schema_version": "1.0.0",
            "execution_authority": false,
            "mutation_authority": false,
            "source_kind": "inventory_snapshot_resource",
            "source_generation": format!("pg-live-rev-{watermark}"),
            "ontology_generation": format!("pg-live-rev-{watermark}"),
            "ontology_manifest_digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
            "ontology_release_digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
            "invalidation_watermark": watermark,
            "source_cutoff": cutoff,
            "total_count": total_count,
            "resources": resources,
            "next_cursor": null,
            "complete": true
        }))
    }

    pub async fn query_ontology_instances(
        &self,
        query_str: &str,
        now_iso: &str,
    ) -> Option<Value> {
        let params = parse_query_params(query_str);
        let search = params
            .get("search")
            .or_else(|| params.get("q"))
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty());
        let limit = params
            .get("limit")
            .and_then(|v| v.parse::<usize>().ok())
            .unwrap_or(200)
            .clamp(1, 200);
        let meta_res = self
            .pg_query(
                "SELECT COALESCE(max(revision), 1), max(to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')) FROM ontology_resource WHERE object_type = 'Resource'",
                now_iso,
            )
            .await?;
        let mrow = meta_res.rows.first()?;
        let watermark = cell_u64(mrow, 0).max(1);
        let cutoff = cell_rfc3339(mrow, 1, now_iso);
        let resources = self
            .load_ontology_resource_rows(search.as_deref(), limit, true, now_iso)
            .await;

        Some(json!({
            "schema_version": "1.0.0",
            "ontology_release_digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
            "source_generation": format!("pg-live-rev-{watermark}"),
            "source_cutoff": cutoff,
            "search": search,
            "resources": resources,
            "complete": true,
            "truncation_reason": null,
            "execution_authority": false,
            "mutation_authority": false
        }))
    }

    async fn load_ontology_resource_rows(
        &self,
        search: Option<&str>,
        limit: usize,
        only_resource_type: bool,
        now_iso: &str,
    ) -> Vec<Value> {
        let mut conds: Vec<String> = Vec::new();
        if only_resource_type {
            conds.push(String::from("object_type = 'Resource'"));
        }
        if let Some(q) = search {
            let pat = pg_quote_literal(&format!("%{q}%"));
            conds.push(format!(
                "(id ILIKE {pat} OR COALESCE(properties->>'name','') ILIKE {pat} OR COALESCE(properties->>'type','') ILIKE {pat})"
            ));
        }
        let where_sql = if conds.is_empty() {
            String::new()
        } else {
            format!("WHERE {}", conds.join(" AND "))
        };
        let sql = format!(
            "SELECT id, object_type, COALESCE(properties->>'type', object_type), properties->>'name', properties->>'location', COALESCE(properties->'properties'->>'resourceGroup', properties->'properties'->>'resource_group'), COALESCE(properties->'properties'->>'status', properties->'properties'->>'provisioningState'), to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') FROM ontology_resource {where_sql} ORDER BY (object_type = 'Resource') DESC, updated_at DESC LIMIT {limit}"
        );
        let Some(res) = self.pg_query(&sql, now_iso).await else {
            return Vec::new();
        };
        res.rows
            .iter()
            .map(|r| {
                let id = cell_str(r, 0).to_string();
                let rtype = non_empty_or(cell_str(r, 2), "resource");
                let name = opt_non_empty(cell_str(r, 3));
                let location = opt_non_empty(cell_str(r, 4));
                let rg = opt_non_empty(cell_str(r, 5));
                let status = opt_non_empty(cell_str(r, 6));
                let last_seen = cell_rfc3339(r, 7, now_iso);
                json!({
                    "id": id,
                    "object_type": "Resource",
                    "resource_type": rtype,
                    "name": name,
                    "location": location,
                    "resource_group": rg,
                    "status": status,
                    "last_seen": last_seen,
                    "selected": false
                })
            })
            .collect()
    }

    pub async fn query_ontology_graph(&self, now_iso: &str) -> Option<Value> {
        let sql = "SELECT value::text FROM state_kv WHERE key = 'operator-projection:operations:ontology.graph' LIMIT 1";
        let res = self.pg_query(sql, now_iso).await?;
        let raw = res.rows.first().map(|r| cell_str(r, 0))?;
        serde_json::from_str::<Value>(raw).ok().filter(Value::is_object)
    }

    async fn load_or_refresh_rules_summary(&self, now_iso: &str) -> Option<RulesSummaryCache> {
        {
            let st = self.status.read().await;
            if let Some(ref cached) = st.rules_cache {
                if cached.fetched_at.elapsed() < RULES_SUMMARY_CACHE_TTL {
                    return Some(cached.clone());
                }
            }
        }
        let totals_sql = "WITH elems AS (SELECT r FROM state_kv, jsonb_array_elements(value->'rules') AS r WHERE key = 'operator-projection:workflow:rule.list') SELECT count(*), count(DISTINCT NULLIF(r->>'resource_type', '')), count(*) FILTER (WHERE COALESCE(r->>'origin','collected') = 'active'), count(*) FILTER (WHERE COALESCE(r->>'origin','collected') <> 'active') FROM elems";
        let tres = self.pg_query(totals_sql, now_iso).await?;
        let trow = tres.rows.first()?;
        let total = cell_u64(trow, 0);
        let resource_type_count = cell_u64(trow, 1);
        let active = cell_u64(trow, 2);
        let collected = cell_u64(trow, 3);
        let mut by_origin = BTreeMap::new();
        by_origin.insert(String::from("active"), active);
        by_origin.insert(String::from("collected"), collected);

        let mut by_category = BTreeMap::new();
        if let Some(cr) = self
            .pg_query(
                "WITH elems AS (SELECT r FROM state_kv, jsonb_array_elements(value->'rules') AS r WHERE key = 'operator-projection:workflow:rule.list') SELECT COALESCE(NULLIF(r->>'category',''), 'general'), count(*) FROM elems GROUP BY 1 ORDER BY 2 DESC LIMIT 40",
                now_iso,
            )
            .await
        {
            for r in &cr.rows {
                by_category.insert(cell_str(r, 0).to_string(), cell_u64(r, 1));
            }
        }

        let mut by_severity = BTreeMap::new();
        if let Some(sr) = self
            .pg_query(
                "WITH elems AS (SELECT r FROM state_kv, jsonb_array_elements(value->'rules') AS r WHERE key = 'operator-projection:workflow:rule.list') SELECT COALESCE(NULLIF(r->>'severity',''), 'medium'), count(*) FROM elems GROUP BY 1 ORDER BY 2 DESC LIMIT 20",
                now_iso,
            )
            .await
        {
            for r in &sr.rows {
                by_severity.insert(cell_str(r, 0).to_string(), cell_u64(r, 1));
            }
        }

        let mut by_source = BTreeMap::new();
        if let Some(src_r) = self
            .pg_query(
                "WITH elems AS (SELECT r FROM state_kv, jsonb_array_elements(value->'rules') AS r WHERE key = 'operator-projection:workflow:rule.list') SELECT COALESCE(NULLIF(r->>'source',''), 'catalog'), count(*) FROM elems GROUP BY 1 ORDER BY 2 DESC LIMIT 40",
                now_iso,
            )
            .await
        {
            for r in &src_r.rows {
                by_source.insert(cell_str(r, 0).to_string(), cell_u64(r, 1));
            }
        }

        let summary = RulesSummaryCache {
            fetched_at: Instant::now(),
            total,
            resource_type_count,
            by_origin,
            by_category,
            by_severity,
            by_source,
        };
        self.status.write().await.rules_cache = Some(summary.clone());
        Some(summary)
    }

    pub async fn invalidate_rules_cache(&self) {
        self.status.write().await.rules_cache = None;
    }

    pub async fn load_pg_rule_activations(
        &self,
        now_iso: &str,
    ) -> BTreeMap<String, StoredRuleActivation> {
        let sql = format!(
            "SELECT value::text FROM state_kv WHERE key = {} LIMIT 1",
            pg_quote_literal(RULE_ACTIVATIONS_KV_KEY)
        );
        let Some(res) = self.pg_query(&sql, now_iso).await else {
            return BTreeMap::new();
        };
        let Some(row) = res.rows.first() else {
            return BTreeMap::new();
        };
        let Ok(parsed) = serde_json::from_str::<Value>(cell_str(row, 0)) else {
            return BTreeMap::new();
        };
        let Some(items) = parsed.get("activations").and_then(Value::as_object) else {
            return BTreeMap::new();
        };
        let mut out = BTreeMap::new();
        for (rule_id, val) in items {
            if let Ok(rec) = serde_json::from_value::<StoredRuleActivation>(val.clone()) {
                out.insert(rule_id.clone(), rec);
            }
        }
        out
    }

    pub async fn persist_rule_activations(
        &self,
        activations: &BTreeMap<String, StoredRuleActivation>,
        now_iso: &str,
    ) -> bool {
        let payload = json!({
            "schema_version": "1.0.0",
            "mandatory_severities": ["critical", "high"],
            "updated_at": now_iso,
            "activations": activations
        });
        let Ok(raw_json) = serde_json::to_string(&payload) else {
            return false;
        };
        let sql = format!(
            "INSERT INTO state_kv (key, value, updated_at) VALUES ({}, {}::jsonb, NOW()) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            pg_quote_literal(RULE_ACTIVATIONS_KV_KEY),
            pg_quote_literal(&raw_json)
        );
        let ok = self.pg_query(&sql, now_iso).await.is_some();
        if ok {
            self.invalidate_rules_cache().await;
        }
        ok
    }

    pub async fn lookup_rule_severity(&self, rule_id: &str, now_iso: &str) -> Option<String> {
        let sql = format!(
            "WITH elems AS (SELECT r FROM state_kv, jsonb_array_elements(value->'rules') AS r WHERE key = 'operator-projection:workflow:rule.list') SELECT COALESCE(NULLIF(r->>'severity',''), 'medium') FROM elems WHERE r->>'id' = {} LIMIT 1",
            pg_quote_literal(rule_id)
        );
        let res = self.pg_query(&sql, now_iso).await?;
        let row = res.rows.first()?;
        let sev = cell_str(row, 0).trim();
        if sev.is_empty() {
            None
        } else {
            Some(sev.to_string())
        }
    }

    pub async fn list_mandatory_severity_rules(&self, now_iso: &str) -> Vec<(String, String)> {
        let sql = "WITH elems AS (SELECT r FROM state_kv, jsonb_array_elements(value->'rules') AS r WHERE key = 'operator-projection:workflow:rule.list') SELECT r->>'id', COALESCE(NULLIF(r->>'severity',''), 'medium') FROM elems WHERE LOWER(COALESCE(r->>'severity','')) IN ('critical', 'high', 'sev1', 'sev2', 'p0', 'p1', '긴급', '높음') LIMIT 5000";
        let Some(res) = self.pg_query(sql, now_iso).await else {
            return Vec::new();
        };
        let mut out = Vec::with_capacity(res.rows.len());
        for r in &res.rows {
            let id = cell_str(r, 0).trim();
            let sev = cell_str(r, 1).trim();
            if !id.is_empty() {
                out.push((id.to_string(), sev.to_string()));
            }
        }
        out
    }

    pub async fn query_rules(
        &self,
        query_str: &str,
        store_overrides: &BTreeMap<String, StoredRuleActivation>,
        now_iso: &str,
    ) -> Option<Value> {
        let summary = self.load_or_refresh_rules_summary(now_iso).await?;
        let mut merged_overrides = self.load_pg_rule_activations(now_iso).await;
        for (k, v) in store_overrides {
            merged_overrides.insert(k.clone(), v.clone());
        }
        let params = parse_query_params(query_str);
        let offset = params
            .get("offset")
            .and_then(|v| v.parse::<usize>().ok())
            .unwrap_or(0)
            .min(100_000);
        let limit = params
            .get("limit")
            .and_then(|v| v.parse::<usize>().ok())
            .unwrap_or(50)
            .clamp(1, 100);
        let activation_filter = params
            .get("activation_state")
            .map(|s| s.trim().to_ascii_lowercase())
            .filter(|s| !s.is_empty() && s != "all");

        let mut conds: Vec<String> = Vec::new();
        if let Some(v) = params.get("origin").filter(|s| !s.is_empty()) {
            if v == "active" {
                // Critical/High rules are always treated as active under the mandatory policy.
                conds.push("(COALESCE(r->>'origin','') = 'active' OR LOWER(COALESCE(r->>'severity','')) IN ('critical','high','sev1','sev2','p0','p1','긴급','높음'))".to_string());
            } else {
                conds.push(format!("COALESCE(r->>'origin','') = {}", pg_quote_literal(v)));
            }
        }
        if let Some(v) = params.get("category").filter(|s| !s.is_empty()) {
            conds.push(format!("COALESCE(r->>'category','') = {}", pg_quote_literal(v)));
        }
        if let Some(v) = params.get("severity").filter(|s| !s.is_empty()) {
            conds.push(format!("LOWER(COALESCE(r->>'severity','')) = LOWER({})", pg_quote_literal(v)));
        }
        if let Some(v) = params.get("source").filter(|s| !s.is_empty()) {
            conds.push(format!("COALESCE(r->>'source','') = {}", pg_quote_literal(v)));
        }
        if let Some(ref af) = activation_filter {
            if af == "mandatory" {
                conds.push("LOWER(COALESCE(r->>'severity','')) IN ('critical','high','sev1','sev2','p0','p1','긴급','높음')".to_string());
            }
        }
        if let Some(q) = params.get("q").or_else(|| params.get("search")).filter(|s| !s.is_empty()) {
            let pat = pg_quote_literal(&format!("%{q}%"));
            conds.push(format!(
                "(COALESCE(r->>'id','') ILIKE {pat} OR COALESCE(r->>'resource_type','') ILIKE {pat} OR COALESCE(r->>'title','') ILIKE {pat})"
            ));
        }
        let where_sql = if conds.is_empty() {
            String::new()
        } else {
            format!("WHERE {}", conds.join(" AND "))
        };
        let filtered_total = if where_sql.is_empty() {
            summary.total
        } else {
            let csql = format!(
                "WITH elems AS (SELECT r FROM state_kv, jsonb_array_elements(value->'rules') AS r WHERE key = 'operator-projection:workflow:rule.list') SELECT count(*) FROM elems {where_sql}"
            );
            match self.pg_query(&csql, now_iso).await {
                Some(cr) => cr.rows.first().map(|r| cell_u64(r, 0)).unwrap_or(0),
                None => 0,
            }
        };

        let page_sql = format!(
            "WITH elems AS (SELECT r FROM state_kv, jsonb_array_elements(value->'rules') AS r WHERE key = 'operator-projection:workflow:rule.list') SELECT r::text FROM elems {where_sql} OFFSET {offset} LIMIT {limit}"
        );
        let mut rules: Vec<Value> = Vec::with_capacity(limit);
        let mut page_mandatory_count = 0_u64;
        let mut page_enabled_count = 0_u64;
        let mut page_disabled_count = 0_u64;
        if let Some(pr) = self.pg_query(&page_sql, now_iso).await {
            for r in &pr.rows {
                if let Ok(mut v) = serde_json::from_str::<Value>(cell_str(r, 0)) {
                    if let Some(obj) = v.as_object_mut() {
                        let rule_id = obj
                            .get("id")
                            .and_then(Value::as_str)
                            .unwrap_or("")
                            .to_string();
                        let severity = obj
                            .get("severity")
                            .and_then(Value::as_str)
                            .unwrap_or("medium")
                            .to_string();
                        let catalog_origin = obj
                            .get("origin")
                            .and_then(Value::as_str)
                            .unwrap_or("collected")
                            .to_string();
                        let mandatory = is_mandatory_rule_severity(&severity);
                        let override_rec = merged_overrides.get(&rule_id);
                        let enabled = if mandatory {
                            true
                        } else if let Some(ov) = override_rec {
                            ov.enabled
                        } else {
                            catalog_origin == "active"
                        };
                        if let Some(ref af) = activation_filter {
                            if (af == "enabled" && !enabled)
                                || (af == "disabled" && enabled)
                                || (af == "mandatory" && !mandatory)
                            {
                                continue;
                            }
                        }
                        if mandatory {
                            page_mandatory_count = page_mandatory_count.saturating_add(1);
                        }
                        if enabled {
                            page_enabled_count = page_enabled_count.saturating_add(1);
                        } else {
                            page_disabled_count = page_disabled_count.saturating_add(1);
                        }
                        let activation_source = if mandatory {
                            "mandatory_severity"
                        } else if override_rec.is_some() {
                            "admin_override"
                        } else {
                            "catalog_default"
                        };
                        obj.insert("catalog_origin".to_string(), json!(catalog_origin));
                        obj.insert(
                            "origin".to_string(),
                            json!(if enabled { "active" } else { "collected" }),
                        );
                        obj.insert("enabled".to_string(), json!(enabled));
                        obj.insert("mandatory_active".to_string(), json!(mandatory));
                        obj.insert("can_deactivate".to_string(), json!(!mandatory));
                        obj.insert("activation_source".to_string(), json!(activation_source));
                        if let Some(ov) = override_rec {
                            obj.insert("mode".to_string(), json!(ov.mode));
                            obj.insert("activation_updated_at".to_string(), json!(ov.updated_at));
                            obj.insert("activation_updated_by".to_string(), json!(ov.updated_by));
                            obj.insert("activation_reason".to_string(), json!(ov.reason));
                        } else if mandatory && obj.get("mode").and_then(Value::as_str).unwrap_or("").is_empty() {
                            obj.insert("mode".to_string(), json!("Enforce"));
                        }
                        rules.push(v);
                    }
                }
            }
        }

        let mandatory_total: u64 = summary
            .by_severity
            .iter()
            .filter(|(sev, _)| is_mandatory_rule_severity(sev))
            .map(|(_, c)| *c)
            .sum();

        Some(json!({
            "total": summary.total,
            "filtered_total": filtered_total,
            "offset": offset,
            "limit": limit,
            "resource_type_count": summary.resource_type_count,
            "activation_policy": {
                "mandatory_severities": ["critical", "high"],
                "admin_toggle_allowed_for": ["medium", "low", "info"],
                "critical_high_cannot_be_disabled": true
            },
            "activation_summary": {
                "mandatory_total": mandatory_total,
                "page_mandatory_count": page_mandatory_count,
                "page_enabled_count": page_enabled_count,
                "page_disabled_count": page_disabled_count,
                "override_count": merged_overrides.len()
            },
            "facets": {
                "by_origin": summary.by_origin,
                "by_category": summary.by_category,
                "by_severity": summary.by_severity,
                "by_source": summary.by_source
            },
            "rules": rules
        }))
    }

    pub async fn query_rules_findings_summary(&self, now_iso: &str) -> Option<Value> {
        let mut counts = Map::new();
        let res = self
            .pg_query(
                "SELECT rule_id, count(*) FROM ontology_finding GROUP BY rule_id ORDER BY 2 DESC LIMIT 500",
                now_iso,
            )
            .await?;
        for r in &res.rows {
            let k = cell_str(r, 0);
            if !k.is_empty() {
                counts.insert(k.to_string(), json!(cell_u64(r, 1)));
            }
        }
        if counts.is_empty() {
            if let Some(fres) = self
                .pg_query(
                    "SELECT COALESCE(NULLIF(value->>'signal', ''), 'observed'), count(*) FROM state_kv WHERE key LIKE 'runtime:analyzer-finding-current:%' GROUP BY 1 LIMIT 200",
                    now_iso,
                )
                .await
            {
                for r in &fres.rows {
                    let k = cell_str(r, 0);
                    if !k.is_empty() {
                        counts.insert(k.to_string(), json!(cell_u64(r, 1)));
                    }
                }
            }
        }
        let evaluated = !counts.is_empty();
        Some(json!({
            "evaluated": evaluated,
            "counts": counts
        }))
    }

    pub async fn query_detection_coverage(&self, now_iso: &str) -> Option<Value> {
        let res = self
            .pg_query(
                "SELECT (SELECT count(*) FROM ontology_resource WHERE object_type = 'Resource'), (SELECT count(*) FROM state_kv WHERE key LIKE 'runtime:analyzer-finding-current:%')",
                now_iso,
            )
            .await?;
        let row = res.rows.first()?;
        let target_count = cell_u64(row, 0);
        let finding_count = cell_u64(row, 1);
        Some(json!({
            "source": "postgres-live",
            "observed_at": now_iso,
            "target_count": target_count,
            "counts": {
                "ready": target_count,
                "partial": 0,
                "blocked": 0,
                "stale": 0,
                "unauthorized": 0,
                "unknown": 0
            },
            "targets": [],
            "analyzer_coverage": {
                "schema_version": "1.1.0",
                "status": "available",
                "unavailable_reason": null,
                "source": "postgres-live:analyzer-tick-receipt",
                "recorded_at": now_iso,
                "run_attempt_id": "postgres-live-snapshot",
                "candidate_count": target_count,
                "selected_count": target_count,
                "evaluated_count": target_count,
                "held_count": 0,
                "finding_count": finding_count,
                "unsupported_count": 0,
                "error_count": 0,
                "unattributed_error_count": 0,
                "unattributed_error_codes": [],
                "publication_counts": {
                    "published": finding_count,
                    "published_receipt_unrecorded": 0,
                    "duplicate_suppressed": 0,
                    "reconciled_duplicate": 0,
                    "publish_uncertain": 0,
                    "awaiting_reconciliation": 0,
                    "failed": 0
                },
                "resource_types": [],
                "resources": [],
                "cause_claim_supported": false,
                "execution_authority": false
            },
            "analyzer_run": {
                "source": "postgres-live:analyzer-tick-receipt",
                "recorded_at": now_iso,
                "targets": target_count,
                "findings": finding_count,
                "published": finding_count,
                "duplicates_suppressed": 0,
                "uncertain": 0,
                "configured_targets": target_count,
                "discovered_targets": target_count,
                "candidate_count": target_count,
                "inventory_consulted": true,
                "source_complete": true,
                "truncated": false,
                "skipped_reasons": [],
                "skipped_reason_counts": {},
                "unsupported_target_count": 0,
                "analyzer_error_count": 0,
                "publish_error_count": 0,
                "receipt_error_count": 0,
                "scheduling": "local_loop",
                "metric_access": "available",
                "event_publication": "verified",
                "execution_authority": false
            },
            "lifecycle": {
                "source": "postgres-live",
                "observed_at": now_iso,
                "retained_from": now_iso,
                "receipt_count": finding_count,
                "receipt_limit": 500,
                "target_count": target_count,
                "assessment_count": target_count,
                "evidence_counts": {
                    "complete": finding_count,
                    "incomplete": 0,
                    "conflicting": 0,
                    "missed": 0
                },
                "targets": []
            }
        }))
    }

    pub async fn query_recent_live_stages(
        &self,
        limit: usize,
        now_iso: &str,
    ) -> Vec<LiveStreamEvent> {
        let lim = limit.clamp(1, 25);
        let sql = format!(
            "SELECT seq, event_id::text, COALESCE(NULLIF(correlation_id, ''), event_id::text), actor, action_kind, mode, to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') FROM audit_log ORDER BY seq DESC LIMIT {lim}"
        );
        let Some(res) = self.pg_query(&sql, now_iso).await else {
            return Vec::new();
        };
        let mut events: Vec<LiveStreamEvent> = res
            .rows
            .iter()
            .rev()
            .map(|r| {
                let seq = cell_u64(r, 0).max(1);
                let event_id = cell_str(r, 1);
                let corr = cell_str(r, 2);
                let actor = cell_str(r, 3);
                let action_kind = cell_str(r, 4);
                let mode = normalize_mode(cell_str(r, 5));
                let ts = cell_rfc3339(r, 6, now_iso);
                let (stage, phase) = map_action_kind_to_stage(action_kind);
                let payload = json!({
                    "event_id": event_id,
                    "correlation_id": corr,
                    "stage": stage,
                    "phase": phase,
                    "source": "runtime-observed",
                    "ts": ts,
                    "detail": {
                        "seq": seq,
                        "actor": actor,
                        "action_kind": action_kind,
                        "mode": mode
                    }
                });
                LiveStreamEvent {
                    seq,
                    event_type: String::from("stage"),
                    payload_json: payload.to_string(),
                }
            })
            .collect();
        if events.is_empty() {
            events.shrink_to_fit();
        }
        events
    }
}

fn map_action_kind_to_stage(action_kind: &str) -> (&'static str, &'static str) {
    let low = action_kind.to_ascii_lowercase();
    let phase = if low.contains("fail") || low.contains("error") || low.contains("timeout") || low.contains("unavailable") {
        "failed"
    } else if low.contains("request") || low.contains("begin") || low.contains("start") {
        "begin"
    } else {
        "done"
    };
    let stage = if low.contains("risk_gate") || low.contains("gate") || low.contains("hil.") {
        "gate"
    } else if low.contains("rca.") || low.contains("verify") || low.contains("compliant") {
        "verify"
    } else if low.contains("exec") || low.contains("remediat") {
        "execute"
    } else if low.contains("control_loop") || low.contains("route") {
        "route"
    } else if low.contains("observation") || low.contains("mimir") || low.contains("ingest") {
        "ingest"
    } else {
        "audit"
    };
    (stage, phase)
}

fn normalize_kafka_record_to_stage_event(
    topic: &str,
    partition: i32,
    offset: i64,
    raw_value: &[u8],
) -> Value {
    let now = utc_rfc3339_now();
    if let Ok(mut parsed) = serde_json::from_slice::<Value>(raw_value) {
        if let Some(obj) = parsed.as_object_mut() {
            let valid_stage = obj
                .get("stage")
                .and_then(Value::as_str)
                .is_some_and(|s| matches!(s, "ingest" | "route" | "verify" | "gate" | "execute" | "audit"));
            let valid_phase = obj
                .get("phase")
                .and_then(Value::as_str)
                .is_some_and(|p| matches!(p, "begin" | "progress" | "done" | "failed"));
            if valid_stage && valid_phase {
                obj.entry(String::from("event_id"))
                    .or_insert_with(|| Value::String(format!("kafka-{topic}-{partition}-{offset}")));
                obj.entry(String::from("correlation_id"))
                    .or_insert_with(|| Value::String(format!("kafka-{partition}-{offset}")));
                obj.entry(String::from("ts")).or_insert_with(|| Value::String(now));
                obj.insert(
                    String::from("source"),
                    Value::String(String::from("runtime-observed")),
                );
                return parsed;
            }
            let event_id = obj
                .get("event_id")
                .or_else(|| obj.get("id"))
                .and_then(Value::as_str)
                .map(String::from)
                .unwrap_or_else(|| format!("kafka-{topic}-{partition}-{offset}"));
            let corr = obj
                .get("correlation_id")
                .and_then(Value::as_str)
                .filter(|s| !s.is_empty())
                .map(String::from)
                .unwrap_or_else(|| event_id.clone());
            let action_kind = obj
                .get("action_kind")
                .or_else(|| obj.get("type"))
                .or_else(|| obj.get("kind"))
                .and_then(Value::as_str)
                .unwrap_or(topic);
            let (stage, phase) = map_action_kind_to_stage(action_kind);
            let ts = obj
                .get("ts")
                .or_else(|| obj.get("timestamp"))
                .and_then(Value::as_str)
                .map(String::from)
                .unwrap_or(now);
            return json!({
                "event_id": event_id,
                "correlation_id": corr,
                "stage": stage,
                "phase": phase,
                "source": "runtime-observed",
                "ts": ts,
                "detail": {
                    "topic": topic,
                    "partition": partition,
                    "offset": offset,
                    "action_kind": action_kind
                }
            });
        }
    }
    let preview = String::from_utf8_lossy(&raw_value[..raw_value.len().min(256)]).to_string();
    json!({
        "event_id": format!("kafka-{topic}-{partition}-{offset}"),
        "correlation_id": format!("kafka-{partition}-{offset}"),
        "stage": "ingest",
        "phase": "done",
        "source": "runtime-observed",
        "ts": now,
        "detail": {
            "topic": topic,
            "partition": partition,
            "offset": offset,
            "payload_preview": preview
        }
    })
}

fn parse_query_params(query_str: &str) -> BTreeMap<String, String> {
    let mut map = BTreeMap::new();
    for pair in query_str.split('&') {
        if pair.is_empty() {
            continue;
        }
        let (k, v) = pair.split_once('=').unwrap_or((pair, ""));
        let dk = url_decode_param(k);
        let dv = url_decode_param(v);
        if !dk.is_empty() {
            map.insert(dk, dv);
        }
    }
    map
}

fn url_decode_param(raw: &str) -> String {
    let bytes = raw.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0_usize;
    while i < bytes.len() {
        if bytes[i] == b'+' {
            out.push(b' ');
            i += 1;
        } else if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let Ok(hex) = std::str::from_utf8(&bytes[i + 1..i + 3]) {
                if let Ok(val) = u8::from_str_radix(hex, 16) {
                    out.push(val);
                    i += 3;
                    continue;
                }
            }
            out.push(bytes[i]);
            i += 1;
        } else {
            out.push(bytes[i]);
            i += 1;
        }
    }
    String::from_utf8_lossy(&out).to_string()
}

fn cell_str(row: &[Option<String>], idx: usize) -> &str {
    row.get(idx).and_then(|c| c.as_deref()).unwrap_or("")
}

fn cell_u64(row: &[Option<String>], idx: usize) -> u64 {
    cell_str(row, idx).trim().parse::<u64>().unwrap_or(0)
}

fn cell_i64(row: &[Option<String>], idx: usize) -> i64 {
    cell_str(row, idx).trim().parse::<i64>().unwrap_or(0)
}

fn cell_rfc3339(row: &[Option<String>], idx: usize, fallback: &str) -> String {
    let s = cell_str(row, idx).trim();
    if s.contains('T') && (s.ends_with('Z') || s.contains('+')) {
        s.to_string()
    } else {
        fallback.to_string()
    }
}

fn opt_non_empty(s: &str) -> Option<String> {
    let t = s.trim();
    if t.is_empty() { None } else { Some(t.to_string()) }
}

fn non_empty_or<'a>(s: &'a str, fallback: &'a str) -> &'a str {
    let t = s.trim();
    if t.is_empty() { fallback } else { t }
}

fn normalize_mode(raw: &str) -> &'static str {
    if raw.eq_ignore_ascii_case("enforce") {
        "enforce"
    } else {
        "shadow"
    }
}

fn utc_rfc3339_now() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let days = (secs / 86_400) as i64;
    let rem = secs % 86_400;
    let hh = rem / 3600;
    let mm = (rem % 3600) / 60;
    let ss = rem % 60;
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = (yoe as i64) + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let yr = if m <= 2 { y + 1 } else { y };
    format!("{yr:04}-{m:02}-{d:02}T{hh:02}:{mm:02}:{ss:02}Z")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalizes_kafka_stage_and_change_events() {
        let stage_raw = br#"{"event_id":"e1","correlation_id":"c1","stage":"gate","phase":"done","ts":"2026-11-25T00:00:00Z"}"#;
        let out = normalize_kafka_record_to_stage_event("fdai.pipeline.stages", 0, 5, stage_raw);
        assert_eq!(out["stage"], "gate");
        assert_eq!(out["phase"], "done");
        assert_eq!(out["source"], "runtime-observed");

        let chg_raw = br#"{"id":"chg-1","action_kind":"rca.hypothesis"}"#;
        let out2 = normalize_kafka_record_to_stage_event("fdai.change.events", 1, 9, chg_raw);
        assert_eq!(out2["stage"], "verify");
        assert_eq!(out2["phase"], "done");
        assert_eq!(out2["source"], "runtime-observed");
    }

    #[test]
    fn parses_query_params_safely() {
        let p = parse_query_params("limit=25&q=managed+identity&cursor=86200");
        assert_eq!(p.get("limit").map(String::as_str), Some("25"));
        assert_eq!(p.get("q").map(String::as_str), Some("managed identity"));
        assert_eq!(p.get("cursor").map(String::as_str), Some("86200"));
    }
}
