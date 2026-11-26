//! Production RemoteAuth, TrustedHost/Redirect, Correlation-ID, Metrics Guard, and PostgreSQL Hub Ledger.

use crate::auth::{AuthError, OperatorAuthenticator};
use axum::http::header::{self, HeaderName};
use axum::http::{HeaderMap, Method, StatusCode};
use fdai_adapter_postgres::{pg_quote_literal, PgConnectionConfig, PgWireClient};
use serde_json::{json, Value};
use std::collections::BTreeSet;
use std::net::IpAddr;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};
use subtle::ConstantTimeEq as _;

static CORRELATION_SEQ: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug)]
pub struct HubRemotePolicy {
    pub service_id: String,
    pub remote_origin: Option<String>,
    pub tenant_id: Option<String>,
    pub spa_client_id: Option<String>,
    pub operator_scope: Option<String>,
    pub operator_ids: BTreeSet<String>,
    pub public_catalog_export: bool,
    pub allowed_hosts: BTreeSet<String>,
    pub redirect_hosts: BTreeSet<String>,
    pub metrics_bearer: Option<String>,
}

impl HubRemotePolicy {
    #[must_use]
    pub fn from_env(service_id: &str) -> Self {
        let origin_env = match service_id {
            "release-hub" => std::env::var("FDAI_RELEASE_HUB_REMOTE_ORIGIN").ok(),
            "hub" => std::env::var("FDAI_LIFECYCLE_HUB_REMOTE_ORIGIN").ok(),
            _ => None,
        }
        .or_else(|| std::env::var("FDAI_HUB_REMOTE_ORIGIN").ok())
        .map(|s| s.trim().trim_end_matches('/').to_string())
        .filter(|s| !s.is_empty());

        let tenant_id = std::env::var("FDAI_ENTRA_TENANT_ID")
            .ok()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty());
        let spa_client_id = std::env::var("FDAI_HUB_SPA_CLIENT_ID")
            .or_else(|_| std::env::var("FDAI_API_AUDIENCE"))
            .ok()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty());
        let operator_scope = std::env::var("FDAI_HUB_OPERATOR_SCOPE")
            .ok()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty());

        let operator_ids: BTreeSet<String> = std::env::var("FDAI_HUB_OPERATOR_IDS")
            .unwrap_or_default()
            .split(',')
            .map(|s| s.trim().to_ascii_lowercase())
            .filter(|s| !s.is_empty())
            .collect();

        let public_catalog_export = std::env::var("FDAI_HUB_PUBLIC_CATALOG_EXPORT")
            .ok()
            .is_some_and(|v| matches!(v.trim().to_ascii_lowercase().as_str(), "1" | "true" | "yes"));

        let mut allowed_hosts: BTreeSet<String> = std::env::var("FDAI_HUB_ALLOWED_HOSTS")
            .unwrap_or_default()
            .split(',')
            .map(|s| s.trim().to_ascii_lowercase())
            .filter(|s| !s.is_empty())
            .collect();
        if let Some(ref orig) = origin_env {
            if let Some(host) = extract_origin_host(orig) {
                allowed_hosts.insert(host);
            }
        }
        let redirect_hosts: BTreeSet<String> = std::env::var("FDAI_HUB_REDIRECT_HOSTS")
            .unwrap_or_default()
            .split(',')
            .map(|s| s.trim().to_ascii_lowercase())
            .filter(|s| !s.is_empty())
            .collect();

        let metrics_bearer = std::env::var("FDAI_METRICS_BEARER")
            .ok()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty());

        Self {
            service_id: service_id.to_string(),
            remote_origin: origin_env,
            tenant_id,
            spa_client_id,
            operator_scope,
            operator_ids,
            public_catalog_export,
            allowed_hosts,
            redirect_hosts,
            metrics_bearer,
        }
    }

    #[must_use]
    pub fn is_remote_mode(&self) -> bool {
        self.remote_origin.is_some() || self.tenant_id.is_some()
    }

    #[must_use]
    pub fn auth_config_json(&self, entra_extra: Option<Value>) -> Value {
        if self.is_remote_mode() {
            let mut doc = json!({
                "profile": "remote-development",
                "tenant_id": self.tenant_id,
                "spa_client_id": self.spa_client_id,
                "operator_scope": self.operator_scope,
                "origin": self.remote_origin,
                "public_catalog_export": self.public_catalog_export,
            });
            if let (Some(e), Some(obj)) = (entra_extra, doc.as_object_mut()) {
                obj.insert(String::from("entra"), e);
            }
            doc
        } else if let Some(e) = entra_extra {
            json!({ "profile": "local-development", "entra": e })
        } else {
            json!({ "profile": "local-development" })
        }
    }
}

fn extract_origin_host(origin: &str) -> Option<String> {
    let rest = origin
        .strip_prefix("https://")
        .or_else(|| origin.strip_prefix("http://"))?;
    let authority = rest.split('/').next()?;
    let host = if authority.starts_with('[') {
        authority.split(']').next().map(|h| format!("{h}]"))?
    } else {
        authority.split(':').next()?.to_string()
    };
    Some(host.to_ascii_lowercase())
}

fn strip_port_from_host_header(host_hdr: &str) -> String {
    let h = host_hdr.trim().to_ascii_lowercase();
    if let Some(rest) = h.strip_prefix('[') {
        if let Some(end) = rest.find(']') {
            return rest[..end].to_string();
        }
    }
    h.split(':').next().unwrap_or("").to_string()
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum HostCheckOutcome {
    Allowed,
    RedirectPermanent(String),
    UntrustedHost,
}

#[must_use]
pub fn check_trusted_host(
    headers: &HeaderMap,
    method: &Method,
    path_and_query: &str,
    policy: &HubRemotePolicy,
) -> HostCheckOutcome {
    let Some(host_raw) = headers.get(header::HOST).and_then(|v| v.to_str().ok()) else {
        return HostCheckOutcome::Allowed;
    };
    let host_only = strip_port_from_host_header(host_raw);
    if host_only.is_empty() {
        return HostCheckOutcome::UntrustedHost;
    }
    if policy.redirect_hosts.contains(&host_only) {
        if matches!(*method, Method::GET | Method::HEAD) {
            if let Some(ref target) = policy.remote_origin {
                return HostCheckOutcome::RedirectPermanent(format!("{target}{path_and_query}"));
            }
        }
        return HostCheckOutcome::UntrustedHost;
    }
    if !policy.allowed_hosts.is_empty() {
        return if policy.allowed_hosts.contains(&host_only) {
            HostCheckOutcome::Allowed
        } else {
            HostCheckOutcome::UntrustedHost
        };
    }
    if policy.is_remote_mode() {
        return HostCheckOutcome::Allowed;
    }
    let is_loopback = host_only == "localhost"
        || host_only == "127.0.0.1"
        || host_only == "::1"
        || host_only.parse::<IpAddr>().is_ok_and(|ip| ip.is_loopback());
    if is_loopback {
        HostCheckOutcome::Allowed
    } else {
        HostCheckOutcome::UntrustedHost
    }
}

/// Enforce Entra RS256 JWT / Bearer authentication when remote mode is active.
/// Returns `Ok(Some(principal))` if authenticated via Bearer token, `Ok(None)` if local/public,
/// or `Err((status, reason))` if denied (fail-closed 401/403).
pub async fn enforce_hub_remote_auth(
    authenticator: &OperatorAuthenticator,
    policy: &HubRemotePolicy,
    headers: &HeaderMap,
    method: &Method,
    path: &str,
    is_release_hub: bool,
) -> Result<Option<String>, (StatusCode, String)> {
    if !policy.is_remote_mode() {
        return Ok(None);
    }
    if matches!(path, "/healthz" | "/readyz" | "/auth/config") {
        return Ok(None);
    }
    if is_release_hub && policy.public_catalog_export {
        let is_public_get = matches!(*method, Method::GET | Method::HEAD)
            && matches!(path, "/v1/catalog/export" | "/v1/catalog/metadata" | "/v1/catalog/public-key");
        let is_public_intake = *method == Method::POST && path == "/v1/deployment-requests";
        if is_public_get || is_public_intake {
            return Ok(None);
        }
    }
    let auth_hdr = headers.get(header::AUTHORIZATION).and_then(|v| v.to_str().ok());
    match authenticator.authenticate(auth_hdr).await {
        Ok(id) => {
            if !policy.operator_ids.is_empty() {
                let principal_low = id.principal.subject_id.to_ascii_lowercase();
                let name_low = id.username.as_deref().unwrap_or("").to_ascii_lowercase();
                if !policy.operator_ids.contains(&principal_low)
                    && (name_low.is_empty() || !policy.operator_ids.contains(&name_low))
                {
                    return Err((StatusCode::FORBIDDEN, String::from("operator_not_allowlisted")));
                }
            }
            Ok(Some(id.principal.subject_id))
        }
        Err(AuthError::Unauthenticated(m)) => Err((StatusCode::UNAUTHORIZED, m)),
        Err(AuthError::Forbidden(m)) => Err((StatusCode::FORBIDDEN, m)),
    }
}

#[must_use]
pub fn check_metrics_bearer(headers: &HeaderMap, policy: &HubRemotePolicy) -> bool {
    let Some(ref expected) = policy.metrics_bearer else {
        return true;
    };
    let provided = headers
        .get(header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "))
        .unwrap_or("");
    constant_time_eq_str(provided, expected)
}

#[must_use]
pub fn constant_time_eq_str(a: &str, b: &str) -> bool {
    a.len() == b.len() && bool::from(a.as_bytes().ct_eq(b.as_bytes()))
}

#[must_use]
pub fn resolve_or_generate_correlation_id(headers: &HeaderMap) -> String {
    if let Some(raw) = headers.get(HeaderName::from_static("x-correlation-id")).and_then(|v| v.to_str().ok()) {
        let cleaned: String = raw
            .trim()
            .chars()
            .filter(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
            .take(64)
            .collect();
        if !cleaned.is_empty() {
            return cleaned;
        }
    }
    let ts = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis()).unwrap_or(0);
    let seq = CORRELATION_SEQ.fetch_add(1, Ordering::Relaxed);
    format!("corr-{ts:x}-{seq:x}")
}

pub fn log_structured_hub_event(service: &str, level: &str, event: &str, correlation_id: &str, detail: &str) {
    let safe_detail: String = detail
        .chars()
        .filter(|c| !c.is_control())
        .take(240)
        .collect();
    let rec = json!({
        "service": service,
        "level": level,
        "event": event,
        "correlation_id": correlation_id,
        "detail": safe_detail,
    });
    eprintln!("{rec}");
}

/// Optional PostgreSQL dual-backend state ledger for multi-replica production deployments.
#[derive(Clone, Debug)]
pub struct HubPgLedger {
    pub cfg: PgConnectionConfig,
    pub table_name: String,
}

impl HubPgLedger {
    #[must_use]
    pub fn from_env(service_id: &str) -> Option<Self> {
        let dsn = match service_id {
            "release-hub" => std::env::var("FDAI_RELEASE_HUB_DATABASE_URL").ok(),
            "hub" => std::env::var("FDAI_LIFECYCLE_HUB_DATABASE_URL").ok(),
            _ => None,
        }
        .or_else(|| std::env::var("FDAI_HUB_DATABASE_URL").ok())
        .filter(|s| !s.trim().is_empty())?;
        let cfg = PgConnectionConfig::from_dsn(&dsn).ok()?;
        let table_name = match service_id {
            "release-hub" => String::from("fdai_release_hub_state_ledger"),
            "hub" => String::from("fdai_lifecycle_hub_state_ledger"),
            _ => String::from("fdai_hub_state_ledger"),
        };
        Some(Self { cfg, table_name })
    }

    pub async fn ensure_schema(&self) -> Result<(), String> {
        let ddl = format!(
            "CREATE TABLE IF NOT EXISTS {} (singleton_id SMALLINT PRIMARY KEY CHECK (singleton_id = 1), revision BIGINT NOT NULL, state_json TEXT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());",
            self.table_name
        );
        PgWireClient::query_once(&self.cfg, &ddl).await.map(|_| ())
    }

    pub async fn load_state_json(&self) -> Result<Option<String>, String> {
        self.ensure_schema().await?;
        let sql = format!(
            "SELECT state_json FROM {} WHERE singleton_id = 1 LIMIT 1;",
            self.table_name
        );
        let res = PgWireClient::query_once(&self.cfg, &sql).await?;
        Ok(res.rows.first().and_then(|r| r.first()).and_then(Clone::clone))
    }

    pub async fn save_state_json(&self, revision: u64, state_json: &str) -> Result<(), String> {
        self.ensure_schema().await?;
        let quoted = pg_quote_literal(state_json);
        let rev_i64 = i64::try_from(revision).unwrap_or(i64::MAX);
        let sql = format!(
            "INSERT INTO {} (singleton_id, revision, state_json, updated_at) VALUES (1, {rev_i64}, {quoted}, NOW()) ON CONFLICT (singleton_id) DO UPDATE SET revision = EXCLUDED.revision, state_json = EXCLUDED.state_json, updated_at = NOW() WHERE {}.revision <= EXCLUDED.revision;",
            self.table_name, self.table_name
        );
        PgWireClient::query_once(&self.cfg, &sql).await.map(|_| ())
    }

    pub async fn check_ready(&self) -> bool {
        PgWireClient::query_once(&self.cfg, "SELECT 1;")
            .await
            .is_ok()
    }
}
