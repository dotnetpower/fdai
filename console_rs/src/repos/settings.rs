//! Domain 6 (`settings`, 8 panels + SettingsOverlay) PostgreSQL repository.
//!
//! Queries real tables (`state_kv`, `operational_retention_policy`, `mcp_catalog_state`,
//! `licensing_entitlement_state`, `llm_invocation`, `audit_log`, `user_preference`,
//! `operator_memory`, `user_memory_fact`, `briefing_subscription`, `process_runtime`,
//! `memory_compaction_candidate`, `mcp_server`, `channel_identity_link`,
//! `channel_pairing_request`) in read-only transactions without exposing secrets or DSNs.

use crate::db::{cell_i64, cell_str, DbHandle};
use fdai_adapter_postgres::pg_quote_literal;
use serde_json::{json, Value};

fn parse_json_cell(row: &[Option<String>], idx: usize) -> Option<Value> {
    let raw = row.get(idx)?.as_deref()?;
    serde_json::from_str::<Value>(raw).ok()
}

fn cell_bool(row: &[Option<String>], idx: usize) -> Option<bool> {
    match row.get(idx)?.as_deref()? {
        "t" | "true" | "TRUE" | "1" => Some(true),
        "f" | "false" | "FALSE" | "0" => Some(false),
        _ => None,
    }
}

pub async fn fetch_kv_exact(db: &DbHandle, key: &str) -> Result<Option<(Value, String)>, String> {
    let q_key = pg_quote_literal(key);
    let sql = format!(
        "SELECT value::text, to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
         FROM state_kv WHERE key = {q_key} LIMIT 1"
    );
    let res = db.query_single_readonly(&sql).await?;
    let Some(row) = res.rows.first() else {
        return Ok(None);
    };
    let val = parse_json_cell(row, 0).unwrap_or(Value::Null);
    let updated_at = cell_str(row, 1);
    Ok(Some((val, updated_at)))
}

async fn fetch_kv_prefix_latest(
    db: &DbHandle,
    prefix: &str,
) -> Result<Option<(String, Value, String)>, String> {
    let mut escaped = String::with_capacity(prefix.len() + 1);
    for ch in prefix.chars() {
        if matches!(ch, '%' | '_' | '\\') {
            escaped.push('\\');
        }
        escaped.push(ch);
    }
    escaped.push('%');
    let q_pat = pg_quote_literal(&escaped);
    let sql = format!(
        "SELECT key, value::text, to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
         FROM state_kv WHERE key LIKE {q_pat} ESCAPE '\\' \
         ORDER BY updated_at DESC LIMIT 1"
    );
    let res = db.query_single_readonly(&sql).await?;
    let Some(row) = res.rows.first() else {
        return Ok(None);
    };
    let key = cell_str(row, 0);
    let val = parse_json_cell(row, 1).unwrap_or(Value::Null);
    let updated_at = cell_str(row, 2);
    Ok(Some((key, val, updated_at)))
}

async fn fetch_kv_prefix_list(
    db: &DbHandle,
    prefix: &str,
    limit: usize,
) -> Result<Vec<(String, Value, String)>, String> {
    let mut escaped = String::with_capacity(prefix.len() + 1);
    for ch in prefix.chars() {
        if matches!(ch, '%' | '_' | '\\') {
            escaped.push('\\');
        }
        escaped.push(ch);
    }
    escaped.push('%');
    let q_pat = pg_quote_literal(&escaped);
    let lim = limit.clamp(1, 50);
    let sql = format!(
        "SELECT key, value::text, to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
         FROM state_kv WHERE key LIKE {q_pat} ESCAPE '\\' \
         ORDER BY updated_at DESC LIMIT {lim}"
    );
    let res = db.query_single_readonly(&sql).await?;
    let mut out = Vec::with_capacity(res.rows.len());
    for row in &res.rows {
        let key = cell_str(row, 0);
        let val = parse_json_cell(row, 1).unwrap_or(Value::Null);
        let updated_at = cell_str(row, 2);
        out.push((key, val, updated_at));
    }
    Ok(out)
}

async fn fetch_retention_policies(db: &DbHandle) -> Result<Vec<Value>, String> {
    let sql = "SELECT policy_id, fact_family, purpose, hot_retention_seconds, warm_retention_seconds, \
               archive_class, deletion_method, \
               to_char(review_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
               to_char(recorded_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
               FROM operational_retention_policy ORDER BY policy_id LIMIT 50";
    let res = db.query_single_readonly(sql).await?;
    Ok(res
        .rows
        .iter()
        .map(|r| {
            json!({
                "policy_id": cell_str(r, 0),
                "fact_family": cell_str(r, 1),
                "purpose": cell_str(r, 2),
                "hot_retention_seconds": cell_i64(r, 3),
                "warm_retention_seconds": cell_i64(r, 4),
                "archive_class": cell_str(r, 5),
                "deletion_method": cell_str(r, 6),
                "review_at": cell_str(r, 7),
                "recorded_at": cell_str(r, 8)
            })
        })
        .collect())
}

pub async fn fetch_settings_summary(db: &DbHandle) -> Value {
    let started = std::time::Instant::now();
    let kv_sql = "SELECT key, to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                  FROM state_kv \
                  WHERE key LIKE 'settings:%' \
                     OR key LIKE 'runtime:startup-readiness%' \
                     OR key LIKE 'operator-projection:iam:%' \
                     OR key LIKE 'deploy-preflight:environment-profile%' \
                  ORDER BY updated_at DESC LIMIT 60";
    let ret_sql = "SELECT count(*) FROM operational_retention_policy";
    let mcp_sql = "SELECT count(*), coalesce(max(revision), 0), \
                   coalesce(to_char(max(updated_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') \
                   FROM mcp_catalog_state";
    let lic_sql = "SELECT count(*), coalesce(max(notice), 'none'), \
                   coalesce(to_char(max(observed_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '') \
                   FROM licensing_entitlement_state";
    let counts_sql = "SELECT (SELECT count(*) FROM llm_invocation), \
                      (SELECT count(*) FROM audit_log), \
                      (SELECT count(*) FROM state_kv), \
                      pg_size_pretty(pg_database_size(current_database()))";

    let (kv_r, ret_r, mcp_r, lic_r, cnt_r) = tokio::join!(
        db.query_single_readonly(kv_sql),
        db.query_single_readonly(ret_sql),
        db.query_single_readonly(mcp_sql),
        db.query_single_readonly(lic_sql),
        db.query_single_readonly(counts_sql),
    );
    let (Ok(kv), Ok(ret), Ok(mcp), Ok(lic), Ok(cnt)) = (kv_r, ret_r, mcp_r, lic_r, cnt_r) else {
        return db.not_measured("settings", "/api/v4/settings/summary", "postgres_unreachable");
    };

    let db_latency_ms = started.elapsed().as_millis() as u64;
    let mcp_row = mcp.rows.first();
    let lic_row = lic.rows.first();
    let cnt_row = cnt.rows.first();
    json!({
        "measurement_status": "measured",
        "measurement_state": "measured",
        "source": "postgres-direct",
        "db_latency_ms": db_latency_ms,
        "db_size": cnt_row.map(|r| cell_str(r, 3)).unwrap_or_default(),
        "state_kv_total": cnt_row.and_then(|r| cell_i64(r, 2)),
        "settings_keys_count": kv.rows.len(),
        "retention_policy_count": ret.rows.first().and_then(|r| cell_i64(r, 0)),
        "mcp_catalog_count": mcp_row.and_then(|r| cell_i64(r, 0)),
        "mcp_revision": mcp_row.and_then(|r| cell_i64(r, 1)),
        "mcp_updated_at": mcp_row.map(|r| cell_str(r, 2)).unwrap_or_default(),
        "licensing_state_count": lic_row.and_then(|r| cell_i64(r, 0)),
        "licensing_notice": lic_row.map(|r| cell_str(r, 1)).unwrap_or_default(),
        "licensing_observed_at": lic_row.map(|r| cell_str(r, 2)).unwrap_or_default(),
        "llm_invocation_count": cnt_row.and_then(|r| cell_i64(r, 0)),
        "audit_log_count": cnt_row.and_then(|r| cell_i64(r, 1)),
        "recent_keys": kv.rows.iter().take(20).map(|r| json!({
            "key": cell_str(r, 0),
            "updated_at": cell_str(r, 1)
        })).collect::<Vec<_>>()
    })
}

pub async fn fetch_settings_overlay(db: &DbHandle) -> Option<Value> {
    let rt_kv = fetch_kv_exact(db, "operator-projection:iam:runtime-settings");
    let lic_sql = "SELECT notice, to_char(observed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                   FROM licensing_entitlement_state LIMIT 1";
    let mcp_sql = "SELECT revision, to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                   FROM mcp_catalog_state LIMIT 1";
    let actor_sql = "SELECT actor, count(*) FROM audit_log GROUP BY actor ORDER BY count(*) DESC LIMIT 1";

    let (Ok(rt), Ok(lic), Ok(mcp), Ok(actor)) = tokio::join!(
        rt_kv,
        db.query_single_readonly(lic_sql),
        db.query_single_readonly(mcp_sql),
        db.query_single_readonly(actor_sql),
    ) else {
        return None;
    };

    let runtime_obj = rt
        .as_ref()
        .and_then(|(v, _)| v.get("runtime"))
        .cloned()
        .unwrap_or(Value::Null);
    let environment = runtime_obj.get("environment").and_then(Value::as_str);
    let autonomy_default = runtime_obj.get("autonomy_default").and_then(Value::as_str);

    Some(json!({
        "environment": environment,
        "autonomy_default": autonomy_default,
        "licensing_notice": lic.rows.first().map(|r| cell_str(r, 0)).filter(|s| !s.is_empty()),
        "licensing_observed_at": lic.rows.first().map(|r| cell_str(r, 1)).unwrap_or_default(),
        "mcp_revision": mcp.rows.first().and_then(|r| cell_i64(r, 0)),
        "mcp_updated_at": mcp.rows.first().map(|r| cell_str(r, 1)).unwrap_or_default(),
        "primary_observed_actor": actor.rows.first().map(|r| cell_str(r, 0)).filter(|s| !s.is_empty()),
        "db_writes_allowed": db.mutations_allowed()
    }))
}

pub async fn fetch_settings_general(db: &DbHandle) -> Option<Value> {
    let pref_sql = "SELECT principal_id, locale, timezone, share_with_learner, answer_detail, \
                    answer_format, revision, \
                    to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                    FROM user_preference ORDER BY updated_at DESC LIMIT 1";
    let brief_sql = "SELECT count(*), coalesce(max(timezone), '') FROM briefing_subscription";
    let lic_sql = "SELECT notice, to_char(observed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                   FROM licensing_entitlement_state LIMIT 1";

    let (Ok(saved_kv), Ok(rt_kv), Ok(pref_res), Ok(brief_res), Ok(lic_res)) = tokio::join!(
        fetch_kv_exact(db, "settings:general:v1"),
        fetch_kv_exact(db, "operator-projection:iam:runtime-settings"),
        db.query_single_readonly(pref_sql),
        db.query_single_readonly(brief_sql),
        db.query_single_readonly(lic_sql),
    ) else {
        return None;
    };

    let pref_row = pref_res.rows.first();
    let mut locale = pref_row
        .map(|r| cell_str(r, 1))
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "ko".to_string());
    let mut timezone = pref_row
        .map(|r| cell_str(r, 2))
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "Asia/Seoul".to_string());
    let mut share_with_learner = pref_row.and_then(|r| cell_bool(r, 3)).unwrap_or(false);
    let mut answer_detail = pref_row
        .map(|r| cell_str(r, 4))
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "standard".to_string());
    let mut answer_format = pref_row
        .map(|r| cell_str(r, 5))
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "mixed".to_string());
    let mut briefing_hour: i64 = 9;
    let mut opening_briefing = true;
    let mut browser_prefs = json!({
        "reduced_motion": false,
        "collapse_chat_trace": true,
        "show_token_usage": true,
        "capture_model_trace": true
    });
    let mut updated_at = pref_row.map(|r| cell_str(r, 7)).unwrap_or_default();
    let mut persisted_in_kv = false;

    if let Some((kv_val, kv_ts)) = saved_kv {
        persisted_in_kv = true;
        if !kv_ts.is_empty() {
            updated_at = kv_ts;
        }
        if let Some(v) = kv_val.get("locale").and_then(Value::as_str) {
            locale = v.to_string();
        }
        if let Some(v) = kv_val.get("timezone").and_then(Value::as_str) {
            timezone = v.to_string();
        }
        if let Some(v) = kv_val.get("answer_detail").and_then(Value::as_str) {
            answer_detail = v.to_string();
        }
        if let Some(v) = kv_val.get("answer_format").and_then(Value::as_str) {
            answer_format = v.to_string();
        }
        if let Some(v) = kv_val.get("briefing_hour").and_then(Value::as_i64) {
            briefing_hour = v;
        }
        if let Some(v) = kv_val.get("opening_briefing").and_then(Value::as_bool) {
            opening_briefing = v;
        }
        if let Some(v) = kv_val.get("share_with_learner").and_then(Value::as_bool) {
            share_with_learner = v;
        }
        if let Some(bp) = kv_val.get("browser_preferences").and_then(Value::as_object) {
            if let Some(obj) = browser_prefs.as_object_mut() {
                for key in [
                    "reduced_motion",
                    "collapse_chat_trace",
                    "show_token_usage",
                    "capture_model_trace",
                ] {
                    if let Some(b) = bp.get(key).and_then(Value::as_bool) {
                        obj.insert(key.to_string(), Value::Bool(b));
                    }
                }
            }
        }
    }

    let runtime_env = rt_kv
        .as_ref()
        .and_then(|(v, _)| v.pointer("/runtime/environment"))
        .and_then(Value::as_str);
    let runtime_updated = rt_kv.as_ref().map(|(_, ts)| ts.as_str()).unwrap_or("");
    if updated_at.is_empty() {
        updated_at = runtime_updated.to_string();
    }
    let has_persisted_preference = pref_row.is_some() || persisted_in_kv;

    Some(json!({
        "locale": locale,
        "answer_detail": answer_detail,
        "answer_format": answer_format,
        "timezone": timezone,
        "briefing_hour": briefing_hour,
        "opening_briefing": opening_briefing,
        "share_with_learner": share_with_learner,
        "browser_preferences": browser_prefs,
        "environment": runtime_env,
        "persisted_in_kv": persisted_in_kv,
        "has_persisted_preference": has_persisted_preference,
        "user_preference_rows": pref_res.rows.len(),
        "briefing_subscription_count": brief_res.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0),
        "licensing_notice": lic_res.rows.first().map(|r| cell_str(r, 0)).filter(|s| !s.is_empty()),
        "licensing_observed_at": lic_res.rows.first().map(|r| cell_str(r, 1)).unwrap_or_default(),
        "updated_at": updated_at
    }))
}

pub async fn fetch_settings_environment(db: &DbHandle) -> Option<Value> {
    let db_meta_sql = "SELECT pg_size_pretty(pg_database_size(current_database())), \
                       (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database())";
    let lic_sql = "SELECT notice, to_char(observed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                   FROM licensing_entitlement_state LIMIT 1";
    let mcp_sql = "SELECT revision, to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                   FROM mcp_catalog_state LIMIT 1";

    let (
        Ok(env_prof),
        Ok(readiness),
        Ok(rt_kv),
        Ok(retention),
        Ok(db_meta),
        Ok(lic_res),
        Ok(mcp_res),
    ) = tokio::join!(
        fetch_kv_prefix_latest(db, "deploy-preflight:environment-profile"),
        fetch_kv_exact(db, "runtime:startup-readiness:latest"),
        fetch_kv_exact(db, "operator-projection:iam:runtime-settings"),
        fetch_retention_policies(db),
        db.query_single_readonly(db_meta_sql),
        db.query_single_readonly(lic_sql),
        db.query_single_readonly(mcp_sql),
    )
    else {
        return None;
    };

    let runtime_obj = rt_kv
        .as_ref()
        .and_then(|(v, _)| v.get("runtime"))
        .cloned()
        .unwrap_or(Value::Null);
    let venue = runtime_obj.get("environment").and_then(Value::as_str);
    let durable = runtime_obj
        .get("state_store_durable")
        .and_then(Value::as_bool);

    let probes: Vec<Value> = readiness
        .as_ref()
        .and_then(|(v, _)| v.get("results"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let passed_probes = probes
        .iter()
        .filter(|p| p.get("status").and_then(Value::as_str) == Some("passed"))
        .count();
    let failed_probes = probes.len().saturating_sub(passed_probes);

    // Map observed readiness probes into collector-style status cards without fabricating unmeasured values.
    let mut collectors: Vec<Value> = probes
        .iter()
        .map(|p| {
            let probe_id = p
                .get("probe_id")
                .and_then(Value::as_str)
                .unwrap_or("unknown");
            let status_raw = p
                .get("status")
                .and_then(Value::as_str)
                .unwrap_or("not-measured");
            let latency_ms = p.get("latency_ms").and_then(Value::as_f64);
            let observed_at = p.get("observed_at").and_then(Value::as_str).unwrap_or("");
            let failure_class = p.get("failure_class").cloned().unwrap_or(Value::Null);
            let normalized_status = if status_raw == "passed" {
                "live"
            } else {
                "unmeasured"
            };
            json!({
                "id": probe_id,
                "status": normalized_status,
                "probe_status": status_raw,
                "latency_ms": latency_ms,
                "observed_at": observed_at,
                "failure_class": failure_class
            })
        })
        .collect();

    let case_hist_configured = runtime_obj
        .get("case_history_configured")
        .and_then(Value::as_bool);
    if case_hist_configured == Some(false) {
        collectors.push(json!({
            "id": "case-history-collector",
            "status": "unmeasured",
            "probe_status": "not-measured",
            "latency_ms": Value::Null,
            "observed_at": rt_kv.as_ref().map(|(_, ts)| ts.as_str()).unwrap_or(""),
            "failure_class": "case_history_unconfigured"
        }));
    }

    let (profile_key, profile_rev, profile_updated, profile_val) = match env_prof {
        Some((k, v, ts)) => (
            k,
            v.get("revision").and_then(Value::as_i64),
            ts,
            v.get("profile").cloned().unwrap_or(Value::Null),
        ),
        None => (String::new(), None, String::new(), Value::Null),
    };

    Some(json!({
        "venue": venue,
        "state_store": match durable {
            Some(true) => "PostgreSQL :5432 (Durable)",
            Some(false) => "PostgreSQL :5432 (Non-Durable)",
            None => "PostgreSQL :5432"
        },
        "db_size": db_meta.rows.first().map(|r| cell_str(r, 0)).unwrap_or_default(),
        "db_active_connections": db_meta.rows.first().and_then(|r| cell_i64(r, 1)),
        "checked_at": readiness
            .as_ref()
            .map(|(_, ts)| ts.clone())
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| rt_kv.as_ref().map(|(_, ts)| ts.clone()).unwrap_or_default()),
        "runtime": runtime_obj,
        "environment_profile": {
            "key": profile_key,
            "revision": profile_rev,
            "updated_at": profile_updated,
            "profile": profile_val
        },
        "startup_readiness": {
            "total": probes.len(),
            "passed": passed_probes,
            "failed": failed_probes,
            "updated_at": readiness.as_ref().map(|(_, ts)| ts.clone()).unwrap_or_default()
        },
        "collectors": collectors,
        "retention_policies": retention,
        "retention_policy_count": retention.len(),
        "licensing": {
            "notice": lic_res.rows.first().map(|r| cell_str(r, 0)).unwrap_or_else(|| "none".to_string()),
            "observed_at": lic_res.rows.first().map(|r| cell_str(r, 1)).unwrap_or_default()
        },
        "mcp_catalog": {
            "revision": mcp_res.rows.first().and_then(|r| cell_i64(r, 0)),
            "updated_at": mcp_res.rows.first().map(|r| cell_str(r, 1)).unwrap_or_default()
        }
    }))
}

pub async fn fetch_settings_models(db: &DbHandle) -> Option<Value> {
    let usage_sql = "SELECT model_key, tier, mode, capability_id, \
                     count(*) AS calls, \
                     coalesce(sum(prompt_tokens), 0) AS prompt_tokens, \
                     coalesce(sum(completion_tokens), 0) AS completion_tokens, \
                     coalesce(round(sum(cost)::numeric, 6)::text, '0') AS total_cost, \
                     to_char(max(occurred_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') AS last_used \
                     FROM llm_invocation \
                     GROUP BY model_key, tier, mode, capability_id \
                     ORDER BY calls DESC LIMIT 20";
    let total_sql = "SELECT count(*), coalesce(round(sum(cost)::numeric, 6)::text, '0') FROM llm_invocation";

    let (Ok(model_kv), Ok(draft_kv), Ok(usage_res), Ok(total_res)) = tokio::join!(
        fetch_kv_exact(db, "operator-projection:iam:model-settings"),
        fetch_kv_exact(db, "settings:models:t2-draft:v1"),
        db.query_single_readonly(usage_sql),
        db.query_single_readonly(total_sql),
    ) else {
        return None;
    };

    let has_model_settings = model_kv.is_some();
    let (model_val, updated_at) = model_kv.unwrap_or((Value::Null, String::new()));
    let llm_usage: Vec<Value> = usage_res
        .rows
        .iter()
        .map(|r| {
            json!({
                "model_key": cell_str(r, 0),
                "tier": cell_str(r, 1),
                "mode": cell_str(r, 2),
                "capability_id": cell_str(r, 3),
                "calls": cell_i64(r, 4).unwrap_or(0),
                "prompt_tokens": cell_i64(r, 5).unwrap_or(0),
                "completion_tokens": cell_i64(r, 6).unwrap_or(0),
                "total_cost_usd": cell_str(r, 7),
                "last_used": cell_str(r, 8)
            })
        })
        .collect();

    let total_invocations = total_res
        .rows
        .first()
        .and_then(|r| cell_i64(r, 0))
        .unwrap_or(0);
    let total_cost_usd = total_res
        .rows
        .first()
        .map(|r| cell_str(r, 1))
        .unwrap_or_else(|| "0".to_string());

    Some(json!({
        "has_model_settings": has_model_settings,
        "region": model_val.get("region").and_then(Value::as_str),
        "environment": model_val.get("environment").and_then(Value::as_str),
        "narrator": model_val.get("narrator").cloned().unwrap_or(Value::Null),
        "capabilities": model_val.get("capabilities").cloned().unwrap_or_else(|| json!([])),
        "t2_model_policy": model_val.get("t2_model_policy").cloned().unwrap_or(Value::Null),
        "document_ocr": model_val.get("document_ocr").cloned().unwrap_or(Value::Null),
        "discovery": model_val.get("discovery").cloned().unwrap_or(Value::Null),
        "provisioning": model_val.get("provisioning").cloned().unwrap_or(Value::Null),
        "t2_saved_draft": draft_kv.map(|(v, ts)| json!({ "draft": v, "updated_at": ts })).unwrap_or(Value::Null),
        "llm_usage": llm_usage,
        "total_invocations": total_invocations,
        "total_cost_usd": total_cost_usd,
        "updated_at": updated_at
    }))
}

pub async fn fetch_settings_runtime(db: &DbHandle) -> Option<Value> {
    let proc_sql = "SELECT count(*) FROM process_runtime";
    let (Ok(rt_kv), Ok(override_kv), Ok(retention), Ok(proc_res)) = tokio::join!(
        fetch_kv_exact(db, "operator-projection:iam:runtime-settings"),
        fetch_kv_exact(db, "settings:runtime:v1"),
        fetch_retention_policies(db),
        db.query_single_readonly(proc_sql),
    ) else {
        return None;
    };

    let has_persisted_runtime_settings = rt_kv.is_some() || override_kv.is_some();
    let (rt_val, rt_ts) = rt_kv.unwrap_or((Value::Null, String::new()));
    let runtime_obj = rt_val.get("runtime").cloned().unwrap_or(Value::Null);
    let base_revision = rt_val.get("revision").and_then(Value::as_u64);
    let settings_list = rt_val
        .get("settings")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();

    let mut autonomy_profile: Option<String> = runtime_obj
        .get("autonomy_default")
        .and_then(Value::as_str)
        .map(|raw| match raw {
            "shadow" => "multi-operator-shadow".to_string(),
            other => other.to_string(),
        });
    let mut approval_expiry_min: Option<u64> = settings_list
        .iter()
        .find(|s| s.get("key").and_then(Value::as_str) == Some("hil.approval_expiry_minutes"))
        .and_then(|s| s.get("effective_value"))
        .and_then(Value::as_u64);
    let mut turn_budget_sec: Option<u64> = settings_list
        .iter()
        .find(|s| s.get("key").and_then(Value::as_str) == Some("irp.budget_seconds"))
        .and_then(|s| s.get("effective_value"))
        .and_then(Value::as_f64)
        .map(|f| f.round().clamp(10.0, 300.0) as u64);
    let mut batch_concurrency: Option<u64> = settings_list
        .iter()
        .find(|s| s.get("key").and_then(Value::as_str) == Some("irp.batch_concurrency"))
        .and_then(|s| s.get("effective_value"))
        .and_then(Value::as_u64);
    let mut availability_policy: Value = settings_list
        .iter()
        .find(|s| s.get("key").and_then(Value::as_str) == Some("detection.resource_availability"))
        .and_then(|s| s.get("effective_value"))
        .cloned()
        .unwrap_or(Value::Null);
    let mut updated_at = rt_ts;
    let mut revision = base_revision;

    if let Some((ov, ov_ts)) = override_kv {
        if !ov_ts.is_empty() {
            updated_at = ov_ts;
        }
        if let Some(r) = ov.get("revision").and_then(Value::as_u64) {
            revision = Some(r);
        }
        let changes = ov.get("changes").unwrap_or(&ov);
        if let Some(p) = changes.get("autonomy_profile").and_then(Value::as_str) {
            autonomy_profile = Some(p.to_string());
        }
        if let Some(e) = changes.get("approval_expiry_min").and_then(Value::as_u64) {
            approval_expiry_min = Some(e);
        }
        if let Some(b) = changes.get("turn_budget_sec").and_then(Value::as_u64) {
            turn_budget_sec = Some(b);
        }
        if let Some(c) = changes.get("batch_concurrency").and_then(Value::as_u64) {
            batch_concurrency = Some(c);
        }
        if let Some(pol) = changes.get("availability_policy") {
            if pol.is_object() {
                availability_policy = pol.clone();
            }
        }
    }

    Some(json!({
        "has_persisted_runtime_settings": has_persisted_runtime_settings,
        "approval_expiry_measured": approval_expiry_min.is_some(),
        "batch_concurrency_measured": batch_concurrency.is_some(),
        "revision": revision,
        "environment": runtime_obj.get("environment").and_then(Value::as_str),
        "autonomy_profile": autonomy_profile,
        "approval_expiry_min": approval_expiry_min,
        "turn_budget_sec": turn_budget_sec,
        "batch_concurrency": batch_concurrency,
        "availability_policy": availability_policy,
        "runtime": runtime_obj,
        "settings_entries_count": settings_list.len(),
        "retention_policy_count": retention.len(),
        "process_runtime_count": proc_res.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0),
        "updated_at": updated_at
    }))
}

pub async fn fetch_settings_iam(db: &DbHandle) -> Option<Value> {
    let actors_sql = "SELECT actor, count(*) AS events, \
                      to_char(max(created_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') AS last_seen \
                      FROM audit_log \
                      GROUP BY actor \
                      ORDER BY events DESC LIMIT 20";
    let audit_total_sql = "SELECT count(*) FROM audit_log";
    let lic_sql = "SELECT notice, to_char(observed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                   FROM licensing_entitlement_state LIMIT 1";

    let (Ok(rt_kv), Ok(decisions_kv), Ok(actors_res), Ok(total_res), Ok(lic_res)) = tokio::join!(
        fetch_kv_exact(db, "operator-projection:iam:runtime-settings"),
        fetch_kv_prefix_list(db, "settings:iam:decision:", 20),
        db.query_single_readonly(actors_sql),
        db.query_single_readonly(audit_total_sql),
        db.query_single_readonly(lic_sql),
    ) else {
        return None;
    };

    let settings_arr = rt_kv
        .as_ref()
        .and_then(|(v, _)| v.get("settings"))
        .and_then(Value::as_array);
    let human_access_enabled = settings_arr
        .and_then(|arr| {
            arr.iter()
                .find(|s| s.get("key").and_then(Value::as_str) == Some("human_access.enabled"))
        })
        .and_then(|s| s.get("effective_value"))
        .and_then(Value::as_bool);
    let reconciliation_interval_sec = settings_arr
        .and_then(|arr| {
            arr.iter().find(|s| {
                s.get("key").and_then(Value::as_str)
                    == Some("human_access.reconciliation_interval_seconds")
            })
        })
        .and_then(|s| s.get("effective_value"))
        .and_then(Value::as_i64);

    let observed_actors: Vec<Value> = actors_res
        .rows
        .iter()
        .map(|r| {
            let actor = cell_str(r, 0);
            let role = if actor.contains("owner") || actor.contains("admin") {
                "Owner"
            } else if actor.contains("viewer") || actor.contains("audit") {
                "Viewer"
            } else {
                "Operator"
            };
            json!({
                "actor": actor,
                "role": role,
                "events": cell_i64(r, 1).unwrap_or(0),
                "last_seen": cell_str(r, 2)
            })
        })
        .collect();

    let recorded_decisions: Vec<Value> = decisions_kv
        .into_iter()
        .map(|(k, v, ts)| {
            json!({
                "key": k,
                "decision": v,
                "recorded_at": ts
            })
        })
        .collect();

    Some(json!({
        "human_access_enabled": human_access_enabled,
        "reconciliation_interval_seconds": reconciliation_interval_sec,
        "audit_log_total": total_res.rows.first().and_then(|r| cell_i64(r, 0)).unwrap_or(0),
        "observed_actors_count": observed_actors.len(),
        "observed_actors": observed_actors,
        "pending_requests": [],
        "recorded_decisions": recorded_decisions,
        "licensing_notice": lic_res.rows.first().map(|r| cell_str(r, 0)).filter(|s| !s.is_empty()),
        "updated_at": rt_kv.as_ref().map(|(_, ts)| ts.clone()).unwrap_or_default()
    }))
}

fn is_opaque_scope_hash(s: &str) -> bool {
    s.strip_prefix("scope-")
        .is_some_and(|rest| rest.len() >= 8 && rest.chars().all(|c| c.is_ascii_hexdigit()))
}

fn humanize_scope_segment(s: &str) -> String {
    if is_opaque_scope_hash(s) {
        "연결된 Azure 구독".to_string()
    } else {
        s.to_string()
    }
}

fn short_ontology_label(raw_id: &str) -> (String, String) {
    let trimmed = raw_id.trim();
    if trimmed.is_empty() {
        return ("관측 범위".to_string(), "관측 리소스".to_string());
    }
    let parts: Vec<&str> = trimmed.split('/').filter(|s| !s.is_empty()).collect();
    let name = parts.last().copied().unwrap_or(trimmed).to_string();
    let rg = parts
        .windows(2)
        .find(|w| w[0].eq_ignore_ascii_case("resource-group") || w[0].eq_ignore_ascii_case("resourcegroups"))
        .map(|w| w[1].to_string())
        .or_else(|| parts.first().map(|s| (*s).to_string()))
        .unwrap_or_else(|| "관측 범위".to_string());
    (rg, name)
}

pub async fn fetch_settings_integrations(db: &DbHandle) -> Option<Value> {
    let mcp_sql = "SELECT revision, to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                   FROM mcp_catalog_state LIMIT 1";
    let counts_sql = "SELECT \
                      (SELECT count(*) FROM mcp_server), \
                      (SELECT count(*) FROM channel_identity_link), \
                      (SELECT count(*) FROM channel_pairing_request), \
                      (SELECT count(*) FROM ontology_resource WHERE object_type = 'Resource'), \
                      (SELECT coalesce(max(revision), 0) FROM ontology_resource WHERE object_type = 'Resource'), \
                      (SELECT count(*) FROM audit_log)";
    let sample_res_sql = "SELECT id, revision, \
                          to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                          FROM ontology_resource WHERE object_type = 'Resource' \
                          ORDER BY updated_at DESC, id ASC LIMIT 1";
    let actor_sql = "SELECT actor FROM audit_log ORDER BY seq DESC LIMIT 1";

    let (
        Ok(mcp_res),
        Ok(cnt_res),
        Ok(sample_res),
        Ok(actor_res),
        Ok(model_kv),
        Ok(rt_kv),
        Ok(prefs_kv),
        Ok(test_receipts),
    ) = tokio::join!(
        db.query_single_readonly(mcp_sql),
        db.query_single_readonly(counts_sql),
        db.query_single_readonly(sample_res_sql),
        db.query_single_readonly(actor_sql),
        fetch_kv_exact(db, "operator-projection:iam:model-settings"),
        fetch_kv_exact(db, "operator-projection:iam:runtime-settings"),
        fetch_kv_exact(db, "settings:integrations:v1"),
        fetch_kv_prefix_list(db, "settings:integrations:test:", 10),
    )
    else {
        return None;
    };

    let doc_ocr = model_kv
        .as_ref()
        .and_then(|(v, _)| v.get("document_ocr"))
        .cloned()
        .unwrap_or(Value::Null);
    let runtime_obj = rt_kv
        .as_ref()
        .and_then(|(v, _)| v.get("runtime"))
        .cloned()
        .unwrap_or(Value::Null);
    let cnt_row = cnt_res.rows.first();
    let mcp_rev = mcp_res
        .rows
        .first()
        .and_then(|r| cell_i64(r, 0));
    let onto_count = cnt_row.and_then(|r| cell_i64(r, 3)).unwrap_or(0);
    let onto_max_rev = cnt_row.and_then(|r| cell_i64(r, 4)).unwrap_or(0);
    let audit_count = cnt_row.and_then(|r| cell_i64(r, 5)).unwrap_or(0);

    let login_actor = actor_res
        .rows
        .first()
        .map(|r| cell_str(r, 0))
        .filter(|s| !s.is_empty());
    let env_name = runtime_obj.get("environment").and_then(Value::as_str);
    let env_tag = env_name.unwrap_or("unknown");
    let mcp_rev_num = mcp_rev.unwrap_or(0);

    let live_preview = match sample_res.rows.first() {
        Some(r) => {
            let raw_id = cell_str(r, 0);
            let (sample_rg, sample_name) = short_ontology_label(&raw_id);
            let display_rg = humanize_scope_segment(&sample_rg);
            let display_name = humanize_scope_segment(&sample_name);
            let display_scope = if display_rg == display_name {
                display_name.clone()
            } else {
                format!("{display_rg} / {display_name}")
            };
            let sample_updated = cell_str(r, 2);
            let env_ko = match env_name {
                Some("dev") => "개발 환경",
                Some("prod") | Some("production") => "운영 환경",
                Some("staging") => "스테이징 환경",
                Some("local") => "로컬 환경",
                Some(other) => other,
                None => "환경 미측정",
            };
            json!({
                "subject": format!("[FDAI] {display_name} 관측 알림 미리보기 ({env_ko})"),
                "scope": display_scope,
                "raw_scope_id": raw_id,
                "evidence": format!("관측 리소스 {onto_count}건 · 감사 기록 {audit_count}건 · MCP 카탈로그 리비전 {mcp_rev_num}"),
                "text": format!(
                    "Subject: [FDAI] {display_name} operational advisory ({env_tag})\nScope: {display_scope}\nEvidence: resources={onto_count}, rev=#{onto_max_rev}, mcp_rev=#{mcp_rev_num}, audit_log={audit_count}\nAction boundary: Notification only (approval required in Console)"
                ),
                "observed_at": sample_updated,
                "login_actor": login_actor,
                "ontology_resources_count": onto_count,
                "ontology_max_revision": onto_max_rev
            })
        }
        None => json!({
            "subject": Value::Null,
            "scope": Value::Null,
            "evidence": Value::Null,
            "text": Value::Null,
            "observed_at": Value::Null,
            "login_actor": login_actor,
            "ontology_resources_count": onto_count,
            "ontology_max_revision": onto_max_rev
        }),
    };

    let recent_tests: Vec<Value> = test_receipts
        .into_iter()
        .map(|(k, v, ts)| json!({ "key": k, "receipt": v, "recorded_at": ts }))
        .collect();

    Some(json!({
        "mcp_catalog": {
            "revision": mcp_rev,
            "updated_at": mcp_res.rows.first().map(|r| cell_str(r, 1)).unwrap_or_default(),
            "mcp_server_count": cnt_row.and_then(|r| cell_i64(r, 0)).unwrap_or(0)
        },
        "channel_links": {
            "identity_links_count": cnt_row.and_then(|r| cell_i64(r, 1)).unwrap_or(0),
            "pairing_requests_count": cnt_row.and_then(|r| cell_i64(r, 2)).unwrap_or(0),
            "primary_transport_configured": runtime_obj
                .get("primary_transport_configured")
                .and_then(Value::as_bool),
            "auxiliary_transport_configured": runtime_obj
                .get("auxiliary_transport_configured")
                .and_then(Value::as_bool)
        },
        "configured_webhooks": [],
        "document_ocr": doc_ocr,
        "live_preview": live_preview,
        "preferences": prefs_kv.map(|(v, ts)| json!({ "values": v, "updated_at": ts })).unwrap_or(Value::Null),
        "recent_boundary_tests": recent_tests
    }))
}

pub async fn fetch_settings_diagnostics_db(db: &DbHandle) -> Option<Value> {
    let started = std::time::Instant::now();
    let pg_sql = "SELECT pg_size_pretty(pg_database_size(current_database())), \
                  (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()), \
                  current_setting('max_connections'), \
                  (SELECT count(*) FROM audit_log), \
                  (SELECT count(*) FROM llm_invocation), \
                  (SELECT count(*) FROM operational_retention_policy), \
                  (SELECT count(*) FROM state_kv)";

    let (Ok(pg_res), Ok(readiness), Ok(mcp_res)) = tokio::join!(
        db.query_single_readonly(pg_sql),
        fetch_kv_exact(db, "runtime:startup-readiness:latest"),
        db.query_single_readonly("SELECT coalesce(max(revision), 0) FROM mcp_catalog_state"),
    ) else {
        return None;
    };

    let db_latency_ms = started.elapsed().as_millis() as u64;
    let row = pg_res.rows.first()?;
    let db_size = cell_str(row, 0);
    let active_conns = cell_i64(row, 1).unwrap_or(0);
    let max_conns = cell_str(row, 2);
    let audit_count = cell_i64(row, 3).unwrap_or(0);
    let llm_count = cell_i64(row, 4).unwrap_or(0);
    let retention_count = cell_i64(row, 5).unwrap_or(0);
    let state_kv_count = cell_i64(row, 6).unwrap_or(0);
    let mcp_rev = mcp_res
        .rows
        .first()
        .and_then(|r| cell_i64(r, 0))
        .unwrap_or(0);

    let probes: Vec<Value> = readiness
        .as_ref()
        .and_then(|(v, _)| v.get("results"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();

    let find_probe = |id: &str| -> Option<&Value> {
        probes
            .iter()
            .find(|p| p.get("probe_id").and_then(Value::as_str) == Some(id))
    };

    let kafka_probe = find_probe("kafka.round-trip");
    let catalog_probe = find_probe("catalog.load");
    let identity_probe = find_probe("identity.token");
    let audit_chain_probe = find_probe("audit.chain");

    let status_ko = |st: &str| -> &'static str {
        match st {
            "passed" => "정상 통과",
            "failed" => "점검 실패",
            "not-measured" => "미측정",
            _ => "확인 필요",
        }
    };

    let components = vec![
        json!({
            "id": "postgres",
            "name": "PostgreSQL 상태 저장소",
            "measurement_status": "measured",
            "measurement_state": "measured",
            "status": "healthy",
            "detail": format!("실시간 연결됨 · DB 응답 {db_latency_ms}ms · {db_size} · 연결 {active_conns}/{max_conns}"),
            "tech": {
                "endpoint": "localhost:5432",
                "database_size": db_size,
                "db_latency_ms": db_latency_ms,
                "connections": format!("{active_conns}/{max_conns}"),
                "audit_log_count": audit_count,
                "llm_invocation_count": llm_count,
                "retention_policy_count": retention_count
            }
        }),
        match kafka_probe {
            Some(p) => {
                let st = p.get("status").and_then(Value::as_str).unwrap_or("unknown");
                let ms = p
                    .get("latency_ms")
                    .and_then(Value::as_f64)
                    .map(|v| format!("{v:.1} ms"))
                    .unwrap_or_else(|| "—".to_string());
                json!({
                    "id": "event-bus",
                    "name": "이벤트 버스 (Redpanda)",
                    "measurement_status": "measured",
                    "measurement_state": "measured",
                    "status": if st == "passed" { "healthy" } else { "degraded" },
                    "detail": format!("왕복 점검 {} · 응답 {ms}", status_ko(st)),
                    "tech": {
                        "probe_id": "kafka.round-trip",
                        "probe_status": st,
                        "latency_ms": ms
                    }
                })
            }
            None => json!({
                "id": "event-bus",
                "name": "이벤트 버스 (Redpanda)",
                "measurement_status": "not-measured",
                "measurement_state": "not-measured",
                "status": "not-measured",
                "detail": "최근 기동 점검 기록 없음",
                "tech": { "probe_id": "kafka.round-trip", "probe_status": "not-measured" }
            }),
        },
        match catalog_probe {
            Some(p) => {
                let st = p.get("status").and_then(Value::as_str).unwrap_or("unknown");
                json!({
                    "id": "ontology-cache",
                    "name": "온톨로지 · 카탈로그 런타임",
                    "measurement_status": "measured",
                    "measurement_state": "measured",
                    "status": if st == "passed" { "healthy" } else { "degraded" },
                    "detail": format!("카탈로그 로드 {} · 보존 정책 {retention_count}건", status_ko(st)),
                    "tech": {
                        "probe_id": "catalog.load",
                        "probe_status": st,
                        "mcp_revision": mcp_rev,
                        "retention_policy_count": retention_count
                    }
                })
            }
            None => json!({
                "id": "ontology-cache",
                "name": "온톨로지 · 카탈로그 런타임",
                "measurement_status": "not-measured",
                "measurement_state": "not-measured",
                "status": "not-measured",
                "detail": "최근 카탈로그 로드 점검 기록 없음",
                "tech": { "probe_id": "catalog.load", "probe_status": "not-measured" }
            }),
        },
        match identity_probe {
            Some(p) => {
                let st = p.get("status").and_then(Value::as_str).unwrap_or("unknown");
                let audit_st = audit_chain_probe
                    .and_then(|a| a.get("status"))
                    .and_then(Value::as_str)
                    .unwrap_or("not-measured");
                json!({
                    "id": "identity-keyvault",
                    "name": "인증 · 감사 무결성 체인",
                    "measurement_status": "measured",
                    "measurement_state": "measured",
                    "status": if st == "passed" { "healthy" } else { "degraded" },
                    "detail": format!("인증 토큰 {} · 감사 체인 {} · AI 호출 {llm_count}건", status_ko(st), status_ko(audit_st)),
                    "tech": {
                        "identity_probe": "identity.token",
                        "identity_status": st,
                        "audit_chain_probe": "audit.chain",
                        "audit_chain_status": audit_st,
                        "llm_invocation_count": llm_count
                    }
                })
            }
            None => json!({
                "id": "identity-keyvault",
                "name": "인증 · 감사 무결성 체인",
                "measurement_status": "not-measured",
                "measurement_state": "not-measured",
                "status": "not-measured",
                "detail": "최근 인증 토큰 점검 기록 없음",
                "tech": { "identity_probe": "identity.token", "identity_status": "not-measured" }
            }),
        },
    ];

    Some(json!({
        "measurement_status": "measured",
        "measurement_state": "measured",
        "source": "postgres-direct",
        "db_latency_ms": db_latency_ms,
        "postgres": {
            "database_size": db_size,
            "db_latency_ms": db_latency_ms,
            "active_connections": active_conns,
            "max_connections": max_conns,
            "audit_log_count": audit_count,
            "llm_invocation_count": llm_count,
            "retention_policy_count": retention_count,
            "state_kv_count": state_kv_count,
            "mcp_revision": mcp_rev
        },
        "startup_readiness_updated_at": readiness.as_ref().map(|(_, ts)| ts.clone()).unwrap_or_default(),
        "startup_readiness_probe_count": probes.len(),
        "components": components,
        "optional_runtime_profile": {
            "measurement_status": "not-measured",
            "measurement_state": "not-measured",
            "reason": "on_demand_only_never_fabricated_as_zero"
        }
    }))
}

pub async fn fetch_settings_memory(
    db: &DbHandle,
    scope_filter: &str,
    search_q: &str,
) -> Option<Value> {
    let op_mem_sql = "SELECT id::text, scope_kind, scope_ref, category, body, \
                      coalesce(ttl_seconds, 0), \
                      to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                      FROM operator_memory WHERE superseded_by IS NULL \
                      ORDER BY created_at DESC LIMIT 60";
    let user_fact_sql = "SELECT memory_id, category, body, \
                         to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), \
                         coalesce(to_char(expires_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), ''), \
                         CASE WHEN expires_at IS NOT NULL THEN GREATEST(0, CEIL(EXTRACT(EPOCH FROM (expires_at - now())) / 86400.0))::bigint ELSE NULL END \
                         FROM user_memory_fact WHERE superseded_by IS NULL \
                         ORDER BY created_at DESC LIMIT 60";
    let comp_sql = "SELECT candidate_id, scope_kind, scope_ref, category, state, \
                    to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                    FROM memory_compaction_candidate \
                    ORDER BY created_at DESC LIMIT 20";
    let onto_scopes_sql = "SELECT id, object_type, revision, \
                           to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
                           FROM ontology_resource WHERE object_type = 'Resource' \
                           ORDER BY updated_at DESC, id ASC LIMIT 8";
    let onto_cnt_sql = "SELECT count(*) FROM ontology_resource WHERE object_type = 'Resource'";

    let (
        Ok(retention),
        Ok(op_res),
        Ok(user_res),
        Ok(comp_res),
        Ok(onto_res),
        Ok(onto_cnt_res),
        Ok(actions_kv),
    ) = tokio::join!(
        fetch_retention_policies(db),
        db.query_single_readonly(op_mem_sql),
        db.query_single_readonly(user_fact_sql),
        db.query_single_readonly(comp_sql),
        db.query_single_readonly(onto_scopes_sql),
        db.query_single_readonly(onto_cnt_sql),
        fetch_kv_prefix_list(db, "settings:memory:action:", 50),
    )
    else {
        return None;
    };

    let search_lower = search_q.to_ascii_lowercase();
    let mut items: Vec<Value> = Vec::new();

    for r in &op_res.rows {
        let scope_kind = cell_str(r, 1);
        let ttl_sec = cell_i64(r, 5).unwrap_or(0);
        let expires_days: Option<i64> = if ttl_sec > 0 {
            Some((ttl_sec / 86400).max(1))
        } else {
            None
        };
        let item = json!({
            "memory_id": cell_str(r, 0),
            "scope": scope_kind,
            "scope_ref": cell_str(r, 2),
            "category": cell_str(r, 3),
            "body": cell_str(r, 4),
            "expires_days": expires_days,
            "created_at": cell_str(r, 6),
            "source_table": "operator_memory"
        });
        let scope_ok = scope_filter == "all" || scope_kind.eq_ignore_ascii_case(scope_filter);
        let text_ok = search_lower.is_empty()
            || item.to_string().to_ascii_lowercase().contains(&search_lower);
        if scope_ok && text_ok {
            items.push(item);
        }
    }

    for r in &user_res.rows {
        let expires_days = cell_i64(r, 5);
        let item = json!({
            "memory_id": cell_str(r, 0),
            "scope": "resource",
            "scope_ref": cell_str(r, 1),
            "category": cell_str(r, 1),
            "body": cell_str(r, 2),
            "expires_days": expires_days,
            "created_at": cell_str(r, 3),
            "expires_at": cell_str(r, 4),
            "source_table": "user_memory_fact"
        });
        let scope_ok = scope_filter == "all" || scope_filter == "resource";
        let text_ok = search_lower.is_empty()
            || item.to_string().to_ascii_lowercase().contains(&search_lower);
        if scope_ok && text_ok {
            items.push(item);
        }
    }

    let compactions: Vec<Value> = comp_res
        .rows
        .iter()
        .map(|r| {
            json!({
                "candidate_id": cell_str(r, 0),
                "scope": cell_str(r, 1),
                "scope_ref": cell_str(r, 2),
                "category": cell_str(r, 3),
                "state": cell_str(r, 4),
                "created_at": cell_str(r, 5)
            })
        })
        .collect();

    let recent_actions: Vec<Value> = actions_kv
        .into_iter()
        .map(|(k, v, ts)| json!({ "key": k, "action": v, "recorded_at": ts }))
        .collect();

    let observed_ontology_scopes: Vec<Value> = onto_res
        .rows
        .iter()
        .map(|r| {
            let full_id = cell_str(r, 0);
            let (rg, name) = short_ontology_label(&full_id);
            json!({
                "resource_id": full_id,
                "resource_group": rg,
                "resource_name": name,
                "object_type": cell_str(r, 1),
                "revision": cell_i64(r, 2).unwrap_or(0),
                "updated_at": cell_str(r, 3)
            })
        })
        .collect();
    let ontology_resources_count = onto_cnt_res
        .rows
        .first()
        .and_then(|r| cell_i64(r, 0))
        .unwrap_or(0);

    Some(json!({
        "items": items,
        "count": items.len(),
        "operator_memory_count": op_res.rows.len(),
        "user_memory_fact_count": user_res.rows.len(),
        "retention_policies": retention,
        "retention_policy_count": retention.len(),
        "compactions": compactions,
        "compaction_count": compactions.len(),
        "observed_ontology_scopes": observed_ontology_scopes,
        "ontology_resources_count": ontology_resources_count,
        "recent_actions": recent_actions
    }))
}

