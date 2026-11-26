//! Bounded Pure-Rust PostgreSQL execution handle (`fdai-adapter-postgres`).
//! Enforces concurrency limits, query timeouts, loopback write guards, and honest
//! `not-measured` envelopes (never fabricates `0` when offline).

use fdai_adapter_postgres::{pg_quote_literal, PgConnectionConfig, PgQueryResult, PgWireClient};
use serde_json::{json, Value};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::sync::{RwLock, Semaphore};

const MAX_CONCURRENT_PG_QUERIES: usize = 16;
const QUERY_TIMEOUT: Duration = Duration::from_secs(8);

#[derive(Clone, Debug, Default)]
pub struct DbHealthSnapshot {
    pub configured: bool,
    pub reachable: Option<bool>,
    pub last_observed_epoch_s: Option<u64>,
    pub last_error_code: Option<String>,
}

#[derive(Clone)]
pub struct DbHandle {
    cfg: Option<PgConnectionConfig>,
    allow_mutations: bool,
    sem: Arc<Semaphore>,
    health: Arc<RwLock<DbHealthSnapshot>>,
}

fn now_epoch_s() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

impl DbHandle {
    #[must_use]
    pub fn from_env() -> Self {
        let dsn = std::env::var("FDAI_DATABASE_URL")
            .ok()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty());
        let allow_mutations = std::env::var("FDAI_CONSOLE_V4_ALLOW_DB_WRITES")
            .ok()
            .is_some_and(|v| v == "1" || v.eq_ignore_ascii_case("true"));
        Self::from_dsn_opt(dsn.as_deref(), allow_mutations)
    }

    #[must_use]
    pub fn from_env_or_local_runtime(repo_root: &std::path::Path) -> Self {
        let direct = Self::from_env();
        if direct.is_configured() {
            return direct;
        }
        if std::env::var("FDAI_CONSOLE_V4_DISABLE_DOTENV").ok().as_deref() == Some("1") {
            return direct;
        }
        let allow_mutations = std::env::var("FDAI_CONSOLE_V4_ALLOW_DB_WRITES")
            .ok()
            .is_some_and(|v| v == "1" || v.eq_ignore_ascii_case("true"));
        let env_path = repo_root.join(".fdai/local-runtime.env");
        if let Ok(raw) = std::fs::read_to_string(&env_path) {
            for line in raw.lines() {
                let trimmed = line.trim();
                if trimmed.starts_with('#') {
                    continue;
                }
                let stripped = trimmed.strip_prefix("export ").unwrap_or(trimmed).trim();
                if let Some(val) = stripped.strip_prefix("FDAI_DATABASE_URL=") {
                    let unquoted = val.trim().trim_matches('"').trim_matches('\'');
                    if let Ok(cfg) = PgConnectionConfig::from_dsn(unquoted) {
                        let low = cfg.host.trim().to_ascii_lowercase();
                        if low == "127.0.0.1" || low == "localhost" || low == "::1" {
                            return Self::from_dsn_opt(Some(unquoted), allow_mutations);
                        }
                    }
                }
            }
        }
        direct
    }

    #[must_use]
    pub fn from_dsn_opt(dsn: Option<&str>, allow_mutations: bool) -> Self {
        let cfg = dsn.and_then(|s| PgConnectionConfig::from_dsn(s).ok());
        let configured = cfg.is_some();
        Self {
            cfg,
            allow_mutations,
            sem: Arc::new(Semaphore::new(MAX_CONCURRENT_PG_QUERIES)),
            health: Arc::new(RwLock::new(DbHealthSnapshot {
                configured,
                reachable: None,
                last_observed_epoch_s: None,
                last_error_code: None,
            })),
        }
    }

    #[must_use]
    pub fn is_configured(&self) -> bool {
        self.cfg.is_some()
    }

    #[must_use]
    pub fn mutations_allowed(&self) -> bool {
        self.allow_mutations && self.cfg.is_some()
    }

    pub async fn health_snapshot(&self) -> DbHealthSnapshot {
        self.health.read().await.clone()
    }

    pub async fn query_readonly(&self, sql: &str) -> Result<PgQueryResult, String> {
        let Some(cfg) = self.cfg.as_ref() else {
            return Err(String::from("db_unconfigured"));
        };
        let _permit = self
            .sem
            .acquire()
            .await
            .map_err(|_| String::from("db_semaphore_closed"))?;
        let guarded = format!("BEGIN TRANSACTION READ ONLY; {sql}; COMMIT;");
        let run = tokio::time::timeout(QUERY_TIMEOUT, PgWireClient::query_once(cfg, &guarded)).await;
        let ts = now_epoch_s();
        match run {
            Ok(Ok(res)) => {
                let mut st = self.health.write().await;
                st.reachable = Some(true);
                st.last_observed_epoch_s = Some(ts);
                st.last_error_code = None;
                Ok(res)
            }
            Ok(Err(_)) => {
                let mut st = self.health.write().await;
                st.reachable = Some(false);
                st.last_observed_epoch_s = Some(ts);
                st.last_error_code = Some(String::from("pg_query_failed"));
                Err(String::from("pg_query_failed"))
            }
            Err(_) => {
                let mut st = self.health.write().await;
                st.reachable = Some(false);
                st.last_observed_epoch_s = Some(ts);
                st.last_error_code = Some(String::from("pg_query_timeout"));
                Err(String::from("pg_query_timeout"))
            }
        }
    }

    pub async fn query_single_readonly(&self, sql: &str) -> Result<PgQueryResult, String> {
        let Some(cfg) = self.cfg.as_ref() else {
            return Err(String::from("db_unconfigured"));
        };
        let _permit = self
            .sem
            .acquire()
            .await
            .map_err(|_| String::from("db_semaphore_closed"))?;
        let run = tokio::time::timeout(QUERY_TIMEOUT, PgWireClient::query_once(cfg, sql)).await;
        let ts = now_epoch_s();
        match run {
            Ok(Ok(res)) => {
                let mut st = self.health.write().await;
                st.reachable = Some(true);
                st.last_observed_epoch_s = Some(ts);
                st.last_error_code = None;
                Ok(res)
            }
            Ok(Err(_)) => {
                let mut st = self.health.write().await;
                st.reachable = Some(false);
                st.last_observed_epoch_s = Some(ts);
                st.last_error_code = Some(String::from("pg_query_failed"));
                Err(String::from("pg_query_failed"))
            }
            Err(_) => {
                let mut st = self.health.write().await;
                st.reachable = Some(false);
                st.last_observed_epoch_s = Some(ts);
                st.last_error_code = Some(String::from("pg_query_timeout"));
                Err(String::from("pg_query_timeout"))
            }
        }
    }

    pub async fn execute_audited_kv_mutation(
        &self,
        key: &str,
        payload_json: &str,
        actor: &str,
        action_kind: &str,
        idempotency_key: &str,
    ) -> Result<Value, String> {
        if !self.allow_mutations {
            return Err(String::from("db_writes_disabled"));
        }
        let Some(cfg) = self.cfg.as_ref() else {
            return Err(String::from("db_unconfigured"));
        };
        if cfg.port == 5432 && std::env::var("FDAI_ALLOW_RUNTIME_5432_MUTATION").ok().as_deref() != Some("1") {
            return Err(String::from("runtime_5432_write_guard"));
        }
        let _permit = self
            .sem
            .acquire()
            .await
            .map_err(|_| String::from("db_semaphore_closed"))?;
        let q_key = pg_quote_literal(key);
        let q_val = pg_quote_literal(payload_json);
        let audit_key = format!("console-audit:{action_kind}:{idempotency_key}");
        let audit_record = json!({
            "schema_version": "1.0.0",
            "key": key,
            "actor": actor,
            "action_kind": action_kind,
            "idempotency_key": idempotency_key,
            "recorded_epoch_s": now_epoch_s()
        });
        let q_audit_key = pg_quote_literal(&audit_key);
        let q_audit_val = pg_quote_literal(&audit_record.to_string());
        let sql = format!(
            "BEGIN; \
             INSERT INTO state_kv (key, value, updated_at) VALUES ({q_key}, {q_val}::jsonb, NOW()) \
             ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW(); \
             INSERT INTO state_kv (key, value, updated_at) VALUES ({q_audit_key}, {q_audit_val}::jsonb, NOW()) \
             ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW(); \
             COMMIT;"
        );
        tokio::time::timeout(QUERY_TIMEOUT, PgWireClient::query_once(cfg, &sql))
            .await
            .map_err(|_| String::from("pg_mutation_timeout"))??;
        Ok(json!({
            "persisted": true,
            "key": key,
            "actor": actor,
            "action_kind": action_kind,
            "idempotency_key": idempotency_key,
            "audit_persisted": true,
            "audit_enqueued": true,
            "audit_key": audit_key
        }))
    }

    #[must_use]
    pub fn not_measured(&self, domain: &str, endpoint: &str, reason: &str) -> Value {
        json!({
            "measurement_status": "not-measured",
            "source": "postgres-direct",
            "db_configured": self.is_configured(),
            "domain": domain,
            "endpoint": endpoint,
            "reason": reason,
            "items": Value::Null,
            "count": Value::Null
        })
    }
}

#[must_use]
pub fn cell_str(row: &[Option<String>], idx: usize) -> String {
    row.get(idx)
        .and_then(|v| v.as_deref())
        .unwrap_or("")
        .to_string()
}

#[must_use]
pub fn cell_i64(row: &[Option<String>], idx: usize) -> Option<i64> {
    row.get(idx)
        .and_then(|v| v.as_deref())
        .and_then(|s| s.parse::<i64>().ok())
}

#[must_use]
pub fn clamp_limit(raw: Option<usize>, default_lim: usize, max_lim: usize) -> usize {
    raw.unwrap_or(default_lim).clamp(1, max_lim)
}

#[must_use]
pub fn quote_like_contains(raw: &str) -> String {
    let trimmed = raw.trim();
    let mut escaped = String::with_capacity(trimmed.len() + 2);
    escaped.push('%');
    for ch in trimmed.chars().take(128) {
        if matches!(ch, '%' | '_' | '\\') {
            escaped.push('\\');
        }
        if !ch.is_control() {
            escaped.push(ch);
        }
    }
    escaped.push('%');
    pg_quote_literal(&escaped)
}
