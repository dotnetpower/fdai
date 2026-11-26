pub mod migrated;
// Pure-Rust 100% Keyless Azure Managed Identity (AKS Workload Identity OIDC / IMDS / Azure CLI) & Azure OpenAI SSE Adapter.
// Prohibits static `api-key` credentials and hardcoded model names; enforces bounded HTTP response body caps & Single-Flight token refresh.
use fdai_ports::KeylessCloudPort;
use http_body_util::{BodyExt as _, Full, Limited};
use hyper::{body::Bytes, Method, Request};
use hyper_rustls::HttpsConnectorBuilder;
use hyper_util::{client::legacy::Client, rt::TokioExecutor};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::sync::{Mutex, RwLock};

const MAX_HTTP_RESPONSE_BYTES: usize = 4 * 1024 * 1024;
const MAX_TOKEN_RESPONSE_BYTES: usize = 64 * 1024;

#[derive(Clone, Debug)]
struct CachedToken {
    access_token: String,
    expires_at_epoch: u64,
}

#[derive(Clone, Debug)]
pub struct AzureOpenAiConfig {
    pub endpoint: String,
    pub deployment: String,
    pub api_version: String,
    pub token_endpoint_override: Option<String>,
}

impl AzureOpenAiConfig {
    /// Fail-Closed: requires BOTH `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT_NAME` (zero hardcoded model fallback).
    #[must_use]
    pub fn from_env() -> Option<Self> {
        let endpoint = std::env::var("AZURE_OPENAI_ENDPOINT").ok()?.trim().to_string();
        let deployment = std::env::var("AZURE_OPENAI_DEPLOYMENT_NAME").ok()?.trim().to_string();
        if endpoint.is_empty() || deployment.is_empty() {
            return None;
        }
        let api_version = std::env::var("AZURE_OPENAI_API_VERSION")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .unwrap_or_else(|| String::from("2024-10-21"));
        Some(Self {
            endpoint: endpoint.trim_end_matches('/').to_string(),
            deployment,
            api_version,
            token_endpoint_override: std::env::var("FDAI_AZURE_IMDS_ENDPOINT").ok(),
        })
    }
}

pub struct KeylessAzureAdapter {
    token_cache: Arc<RwLock<Option<CachedToken>>>,
    refresh_lock: Arc<Mutex<()>>,
}

impl KeylessAzureAdapter {
    pub fn try_new(api_key: Option<&str>) -> Result<Self, &'static str> {
        if api_key.is_some_and(|k| !k.trim().is_empty()) {
            return Err("api_key prohibited: Azure AD Keyless Managed Identity only");
        }
        Ok(Self {
            token_cache: Arc::new(RwLock::new(None)),
            refresh_lock: Arc::new(Mutex::new(())),
        })
    }

    pub async fn acquire_bearer_token(
        &self,
        resource: &str,
        imds_override: Option<&str>,
    ) -> Result<String, String> {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        if let Some(tok) = self.token_cache.read().await.as_ref() {
            if tok.expires_at_epoch > now + 300 {
                return Ok(tok.access_token.clone());
            }
        }
        let _guard = self.refresh_lock.lock().await;
        if let Some(tok) = self.token_cache.read().await.as_ref() {
            if tok.expires_at_epoch > now + 300 {
                return Ok(tok.access_token.clone());
            }
        }
        let fetched = if let Some(wl) = try_workload_identity_token(resource).await? {
            wl
        } else {
            let imds_url = imds_override.map(String::from).unwrap_or_else(|| {
                format!(
                    "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource={resource}"
                )
            });
            if let Ok(tok) = fetch_imds_token(&imds_url).await {
                tok
            } else {
                fetch_az_cli_token(resource).await?
            }
        };
        let access = fetched.access_token.clone();
        *self.token_cache.write().await = Some(fetched);
        Ok(access)
    }

    pub async fn stream_chat_completions(
        &self,
        cfg: &AzureOpenAiConfig,
        user_prompt: &str,
    ) -> Result<Vec<String>, String> {
        let ep = cfg.endpoint.trim_end_matches('/');
        let ep_safe = ep.starts_with("https://")
            || ep.starts_with("http://127.0.0.1")
            || ep.starts_with("http://[::1]");
        if !ep_safe {
            return Err(String::from("Azure OpenAI endpoint must use HTTPS (loopback HTTP allowed for tests only)"));
        }
        let bearer = self
            .acquire_bearer_token(
                "https://cognitiveservices.azure.com",
                cfg.token_endpoint_override.as_deref(),
            )
            .await?;
        let url = format!(
            "{ep}/openai/deployments/{}/chat/completions?api-version={}",
            cfg.deployment, cfg.api_version
        );
        let payload = serde_json::json!({
            "messages": [
                {"role": "system", "content": "You are the operational intelligence assistant. Respond concisely and factually."},
                {"role": "user", "content": user_prompt}
            ],
            "stream": true,
            "temperature": 0.2
        });
        let https = HttpsConnectorBuilder::new()
            .with_webpki_roots()
            .https_or_http()
            .enable_http1()
            .build();
        let client: Client<_, Full<Bytes>> = Client::builder(TokioExecutor::new()).build(https);
        let req = Request::builder()
            .method(Method::POST)
            .uri(&url)
            .header("Authorization", format!("Bearer {bearer}"))
            .header("Content-Type", "application/json")
            .body(Full::new(Bytes::from(payload.to_string())))
            .map_err(|e| e.to_string())?;
        let resp = tokio::time::timeout(Duration::from_secs(30), client.request(req))
            .await
            .map_err(|_| String::from("Azure OpenAI request timed out"))?
            .map_err(|e| format!("Azure OpenAI HTTP error: {e}"))?;
        if !resp.status().is_success() {
            return Err(format!("Azure OpenAI returned HTTP {}", resp.status().as_u16()));
        }
        let body = Limited::new(resp.into_body(), MAX_HTTP_RESPONSE_BYTES)
            .collect()
            .await
            .map_err(|_| String::from("Azure OpenAI response body exceeded 4 MiB cap"))?
            .to_bytes();
        let text = String::from_utf8_lossy(&body);
        let mut chunks = Vec::new();
        for line in text.lines() {
            let trimmed = line.trim();
            if let Some(data) = trimmed.strip_prefix("data:") {
                let d = data.trim();
                if d.is_empty() || d == "[DONE]" {
                    continue;
                }
                if let Ok(v) = serde_json::from_str::<serde_json::Value>(d) {
                    if let Some(delta) = v
                        .pointer("/choices/0/delta/content")
                        .and_then(serde_json::Value::as_str)
                    {
                        if !delta.is_empty() {
                            chunks.push(delta.to_string());
                        }
                    }
                }
            }
        }
        if chunks.is_empty() {
            if let Ok(v) = serde_json::from_str::<serde_json::Value>(&text) {
                if let Some(msg) = v
                    .pointer("/choices/0/message/content")
                    .and_then(serde_json::Value::as_str)
                {
                    chunks.push(msg.to_string());
                }
            }
        }
        Ok(chunks)
    }
}

fn form_encode(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for b in s.bytes() {
        if b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.' | b'~') {
            out.push(b as char);
        } else {
            out.push_str(&format!("%{b:02X}"));
        }
    }
    out
}

async fn try_workload_identity_token(resource: &str) -> Result<Option<CachedToken>, String> {
    let Ok(token_file) = std::env::var("AZURE_FEDERATED_TOKEN_FILE") else {
        return Ok(None);
    };
    let Ok(client_id) = std::env::var("AZURE_CLIENT_ID") else {
        return Ok(None);
    };
    let Ok(tenant_id) = std::env::var("AZURE_TENANT_ID") else {
        return Ok(None);
    };
    if token_file.trim().is_empty() || client_id.trim().is_empty() || tenant_id.trim().is_empty() {
        return Ok(None);
    }
    let assertion = tokio::fs::read_to_string(token_file.trim())
        .await
        .map_err(|e| format!("failed to read AZURE_FEDERATED_TOKEN_FILE: {e}"))?;
    let authority = std::env::var("AZURE_AUTHORITY_HOST")
        .ok()
        .filter(|s| s.starts_with("https://") || s.starts_with("http://127.0.0.1"))
        .unwrap_or_else(|| String::from("https://login.microsoftonline.com"));
    let url = format!("{}/{}/oauth2/v2.0/token", authority.trim_end_matches('/'), tenant_id.trim());
    let scope = format!("{}/.default", resource.trim_end_matches('/'));
    let form = format!(
        "client_id={}&scope={}&grant_type=client_credentials&client_assertion_type={}&client_assertion={}",
        form_encode(client_id.trim()),
        form_encode(&scope),
        form_encode("urn:ietf:params:oauth:client-assertion-type:jwt-bearer"),
        form_encode(assertion.trim()),
    );
    let https = HttpsConnectorBuilder::new()
        .with_webpki_roots()
        .https_or_http()
        .enable_http1()
        .build();
    let client: Client<_, Full<Bytes>> = Client::builder(TokioExecutor::new()).build(https);
    let req = Request::builder()
        .method(Method::POST)
        .uri(&url)
        .header("Content-Type", "application/x-www-form-urlencoded")
        .body(Full::new(Bytes::from(form)))
        .map_err(|e| e.to_string())?;
    let resp = tokio::time::timeout(Duration::from_secs(10), client.request(req))
        .await
        .map_err(|_| String::from("Workload Identity OIDC timeout"))?
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("Workload Identity OIDC returned HTTP {}", resp.status().as_u16()));
    }
    let bytes = Limited::new(resp.into_body(), MAX_TOKEN_RESPONSE_BYTES)
        .collect()
        .await
        .map_err(|_| String::from("Workload Identity response exceeded 64 KiB cap"))?
        .to_bytes();
    let json: serde_json::Value = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
    let access_token = json
        .get("access_token")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| String::from("Workload Identity missing access_token"))?
        .to_string();
    let expires_in = json.get("expires_in").and_then(serde_json::Value::as_u64).unwrap_or(1800);
    let now = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    Ok(Some(CachedToken { access_token, expires_at_epoch: now + expires_in }))
}

async fn fetch_imds_token(url: &str) -> Result<CachedToken, String> {
    let url_safe = url.starts_with("http://169.254.169.254/")
        || url.starts_with("http://127.0.0.1")
        || url.starts_with("http://[::1]")
        || url.starts_with("https://");
    if !url_safe {
        return Err(String::from("IMDS token URL must target 169.254.169.254, HTTPS, or loopback"));
    }
    let https = HttpsConnectorBuilder::new()
        .with_webpki_roots()
        .https_or_http()
        .enable_http1()
        .build();
    let client: Client<_, Full<Bytes>> = Client::builder(TokioExecutor::new()).build(https);
    let req = Request::builder()
        .method(Method::GET)
        .uri(url)
        .header("Metadata", "true")
        .body(Full::new(Bytes::new()))
        .map_err(|e| e.to_string())?;
    let resp = tokio::time::timeout(Duration::from_secs(3), client.request(req))
        .await
        .map_err(|_| String::from("IMDS timeout"))?
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("IMDS status {}", resp.status().as_u16()));
    }
    let bytes = Limited::new(resp.into_body(), MAX_TOKEN_RESPONSE_BYTES)
        .collect()
        .await
        .map_err(|_| String::from("IMDS response exceeded 64 KiB cap"))?
        .to_bytes();
    let json: serde_json::Value = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
    let token = json
        .get("access_token")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| String::from("missing access_token"))?
        .to_string();
    let expires_at_epoch = json
        .get("expires_on")
        .and_then(|v| v.as_str().and_then(|s| s.parse::<u64>().ok()).or_else(|| v.as_u64()))
        .unwrap_or_else(|| {
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d| d.as_secs() + 1800)
                .unwrap_or(1800)
        });
    Ok(CachedToken { access_token: token, expires_at_epoch })
}

async fn fetch_az_cli_token(resource: &str) -> Result<CachedToken, String> {
    let out = tokio::time::timeout(
        Duration::from_secs(15),
        tokio::process::Command::new("az")
            .args(["account", "get-access-token", "--resource", resource, "--output", "json"])
            .output(),
    )
    .await
    .map_err(|_| String::from("az cli token timeout"))?
    .map_err(|e| format!("az cli exec failed: {e}"))?;
    if !out.status.success() {
        return Err(String::from("az cli returned non-zero status"));
    }
    let json: serde_json::Value = serde_json::from_slice(&out.stdout).map_err(|e| e.to_string())?;
    let token = json
        .get("accessToken")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| String::from("missing accessToken"))?
        .to_string();
    let now = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    Ok(CachedToken { access_token: token, expires_at_epoch: now + 1800 })
}

impl KeylessCloudPort for KeylessAzureAdapter {
    fn is_keyless_managed_identity(&self) -> bool {
        true
    }
}

/// Fail-closed startup role readback check against the canonical FDAI 3-tier Azure IAM catalog.
pub fn verify_startup_standing_roles(
    observed_role_names: &[&str],
) -> Result<fdai_domain_core::azure_iam_catalog::RoleReadbackDecision, String> {
    let catalog = fdai_contracts::azure_iam_groups::load_embedded_azure_iam_catalog()?;
    fdai_domain_core::azure_iam_catalog::validate_azure_iam_catalog(&catalog)
        .map_err(|errs| format!("invalid embedded azure iam catalog: {}", errs.join("; ")))?;
    let decision = fdai_domain_core::azure_iam_catalog::evaluate_standing_role_readback(
        &catalog,
        observed_role_names,
    );
    if !decision.allowed {
        return Err(format!(
            "{}: {}",
            decision.reason,
            decision.overbroad_roles.join(", ")
        ));
    }
    Ok(decision)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpListener;

    #[tokio::test]
    async fn keyless_adapter_rejects_api_key_and_streams_azure_openai_sse() -> Result<(), String> {
        assert!(KeylessAzureAdapter::try_new(Some("sk-secret")).is_err());
        let adapter = KeylessAzureAdapter::try_new(None).map_err(|e| e.to_string())?;
        let listener = TcpListener::bind("127.0.0.1:0").await.map_err(|e| e.to_string())?;
        let port = listener.local_addr().map_err(|e| e.to_string())?.port();
        let srv = tokio::spawn(async move {
            for _ in 0..2 {
                if let Ok((mut s, _)) = listener.accept().await {
                    let mut buf = [0_u8; 4096];
                    let n = s.read(&mut buf).await.unwrap_or(0);
                    let req_s = String::from_utf8_lossy(&buf[..n]);
                    let resp = if req_s.starts_with("GET /token") {
                        let body = r#"{"access_token":"tok-keyless-123","expires_on":"9999999999"}"#;
                        format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len())
                    } else {
                        let body = "data: {\"choices\":[{\"delta\":{\"content\":\"hello \"}}]}\n\ndata: {\"choices\":[{\"delta\":{\"content\":\"world\"}}]}\n\ndata: [DONE]\n\n";
                        format!("HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len())
                    };
                    let _ = s.write_all(resp.as_bytes()).await;
                }
            }
        });
        let cfg = AzureOpenAiConfig {
            endpoint: format!("http://127.0.0.1:{port}"),
            deployment: String::from("configured-deployment"),
            api_version: String::from("2024-10-21"),
            token_endpoint_override: Some(format!("http://127.0.0.1:{port}/token")),
        };
        let chunks = adapter.stream_chat_completions(&cfg, "ping").await?;
        assert_eq!(chunks.concat(), "hello world");
        let _ = srv.await;
        Ok(())
    }

    #[test]
    fn startup_role_readback_accepts_fdai_groups_and_blocks_overbroad_standing_roles() {
        let ok = verify_startup_standing_roles(&["FDAI Reader v1", "FDAI Operator v1"]);
        assert!(ok.is_ok());

        let err = verify_startup_standing_roles(&["FDAI Operator v1", "Contributor"]);
        assert!(err.is_err());
    }
}
