//! Pure-Rust upstream HTTP client for services_rs/operator-service (:8010).
//! Preserves fail-closed and not-measured semantics (never fabricates 0 when offline).

use http_body_util::{BodyExt, Full};
use hyper::body::Bytes;
use hyper::{Method, Request, Uri};
use hyper_util::client::legacy::{connect::HttpConnector, Client};
use hyper_util::rt::TokioExecutor;
use serde_json::{json, Value};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const UPSTREAM_CONNECT_TIMEOUT_MS: u64 = 150;
const UPSTREAM_REQUEST_TIMEOUT_MS: u64 = 2500;
const UPSTREAM_UNREACHABLE_BACKOFF_MS: u64 = 5_000;

fn now_epoch_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

#[derive(Clone)]
pub struct UpstreamClient {
    base_url: String,
    http: Client<HttpConnector, Full<Bytes>>,
    unreachable_until_ms: Arc<AtomicU64>,
}

#[derive(Debug, Clone)]
pub struct UpstreamOutcome {
    pub reachable: bool,
    pub status: u16,
    pub payload: Option<Value>,
}

impl UpstreamClient {
    pub fn new(base_url: String) -> Self {
        let trimmed = base_url.trim_end_matches('/').to_string();
        let mut connector = HttpConnector::new();
        connector.set_connect_timeout(Some(Duration::from_millis(UPSTREAM_CONNECT_TIMEOUT_MS)));
        let http = Client::builder(TokioExecutor::new()).build(connector);
        Self {
            base_url: trimmed,
            http,
            unreachable_until_ms: Arc::new(AtomicU64::new(0)),
        }
    }

    pub fn base_url(&self) -> &str {
        &self.base_url
    }

    pub async fn get_json(&self, path_and_query: &str, auth_header: Option<&str>) -> UpstreamOutcome {
        self.request_json(Method::GET, path_and_query, None, auth_header)
            .await
    }

    pub async fn post_json(
        &self,
        path_and_query: &str,
        body: Value,
        auth_header: Option<&str>,
    ) -> UpstreamOutcome {
        self.request_json(Method::POST, path_and_query, Some(body), auth_header)
            .await
    }

    pub async fn patch_json(
        &self,
        path_and_query: &str,
        body: Value,
        auth_header: Option<&str>,
    ) -> UpstreamOutcome {
        self.request_json(Method::PATCH, path_and_query, Some(body), auth_header)
            .await
    }

    async fn request_json(
        &self,
        method: Method,
        path_and_query: &str,
        body: Option<Value>,
        auth_header: Option<&str>,
    ) -> UpstreamOutcome {
        let now_ms = now_epoch_ms();
        let backoff_until = self.unreachable_until_ms.load(Ordering::Relaxed);
        if backoff_until > now_ms {
            return UpstreamOutcome {
                reachable: false,
                status: 0,
                payload: None,
            };
        }
        let normalized = if path_and_query.starts_with('/') {
            path_and_query.to_string()
        } else {
            format!("/{path_and_query}")
        };
        let full_url = format!("{}{}", self.base_url, normalized);
        let Ok(uri) = full_url.parse::<Uri>() else {
            return UpstreamOutcome {
                reachable: false,
                status: 0,
                payload: None,
            };
        };

        let bytes = match body {
            Some(v) => Bytes::from(v.to_string()),
            None => Bytes::new(),
        };

        let mut builder = Request::builder()
            .method(method)
            .uri(uri)
            .header("accept", "application/json");
        if !bytes.is_empty() {
            builder = builder.header("content-type", "application/json");
        }
        if let Some(auth) = auth_header {
            if !auth.trim().is_empty() {
                builder = builder.header("authorization", auth);
            }
        }
        let Ok(req) = builder.body(Full::new(bytes)) else {
            return UpstreamOutcome {
                reachable: false,
                status: 0,
                payload: None,
            };
        };

        let Ok(Ok(resp)) = tokio::time::timeout(
            Duration::from_millis(UPSTREAM_REQUEST_TIMEOUT_MS),
            self.http.request(req),
        )
        .await
        else {
            self.unreachable_until_ms.store(
                now_epoch_ms().saturating_add(UPSTREAM_UNREACHABLE_BACKOFF_MS),
                Ordering::Relaxed,
            );
            return UpstreamOutcome {
                reachable: false,
                status: 0,
                payload: None,
            };
        };
        self.unreachable_until_ms.store(0, Ordering::Relaxed);

        let status = resp.status().as_u16();
        let Ok(collected) = resp.into_body().collect().await else {
            return UpstreamOutcome {
                reachable: true,
                status,
                payload: None,
            };
        };
        let raw = collected.to_bytes();
        let payload = serde_json::from_slice::<Value>(&raw).ok();
        UpstreamOutcome {
            reachable: true,
            status,
            payload,
        }
    }

    pub fn not_measured_envelope(&self, domain: &str, endpoint: &str, reason: &str) -> Value {
        self.not_measured_with_status(domain, endpoint, 0, reason)
    }

    pub fn not_measured_with_status(
        &self,
        domain: &str,
        endpoint: &str,
        upstream_status: u16,
        reason: &str,
    ) -> Value {
        json!({
            "source": "console-v4-rust",
            "domain": domain,
            "endpoint": endpoint,
            "measurement_state": "not-measured",
            "upstream_status": upstream_status,
            "upstream_url": self.base_url,
            "reason": reason,
            "data": Value::Null
        })
    }
}
