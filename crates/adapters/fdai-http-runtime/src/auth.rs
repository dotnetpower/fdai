//! Entra ID RS256 JWKS, Local Azure CLI, Static Bearer, Dev Mode, and RBAC authentication.

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine as _;
use http_body_util::BodyExt as _;
use hyper::Request;
use hyper_rustls::HttpsConnectorBuilder;
use hyper_util::client::legacy::Client;
use hyper_util::rt::TokioExecutor;
use ring::digest::{digest, SHA256};
use ring::rand::{SecureRandom as _, SystemRandom};
use ring::signature::{RsaPublicKeyComponents, RSA_PKCS1_2048_8192_SHA256};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fmt::Write as _;
use std::net::IpAddr;
use std::process::{Command, Stdio};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use subtle::ConstantTimeEq as _;
use tokio::sync::{Mutex, RwLock};

const BEARER_PREFIX: &str = "Bearer ";
const MAX_AUTH_HEADER_BYTES: usize = 16_384;
const JWT_LEEWAY_SECS: i64 = 60;
const JWKS_CACHE_TTL: Duration = Duration::from_secs(3_600);
const JWKS_FETCH_TIMEOUT: Duration = Duration::from_secs(10);
const AZ_CLI_TIMEOUT: Duration = Duration::from_secs(20);
const MAX_JWKS_BYTES: usize = 512 * 1024;
const ARM_RESOURCE: &str = "https://management.azure.com";

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OperatorRole {
    Reader,
    Contributor,
    Approver,
    Owner,
    BreakGlass,
}

impl OperatorRole {
    #[must_use]
    pub fn parse_str(raw: &str) -> Option<Self> {
        match raw.trim().to_ascii_lowercase().as_str() {
            "reader" => Some(Self::Reader),
            "contributor" => Some(Self::Contributor),
            "approver" => Some(Self::Approver),
            "owner" => Some(Self::Owner),
            "break_glass" | "break-glass" => Some(Self::BreakGlass),
            _ => None,
        }
    }

    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Reader => "reader",
            Self::Contributor => "contributor",
            Self::Approver => "approver",
            Self::Owner => "owner",
            Self::BreakGlass => "break_glass",
        }
    }

    #[must_use]
    pub const fn rank(self) -> i32 {
        match self {
            Self::Reader => 0,
            Self::Contributor => 1,
            Self::Approver => 2,
            Self::Owner => 3,
            Self::BreakGlass => -1,
        }
    }
}

pub const READER_ROLES: [OperatorRole; 4] = [
    OperatorRole::Reader,
    OperatorRole::Contributor,
    OperatorRole::Approver,
    OperatorRole::Owner,
];

pub const CONTRIBUTOR_ROLES: [OperatorRole; 3] = [
    OperatorRole::Contributor,
    OperatorRole::Approver,
    OperatorRole::Owner,
];

pub const APPROVAL_ROLES: [OperatorRole; 2] = [OperatorRole::Approver, OperatorRole::Owner];

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OperatorPrincipalKind {
    Human,
    Workload,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct OperatorPrincipal {
    pub subject_id: String,
    pub roles: BTreeSet<OperatorRole>,
    pub principal_kind: OperatorPrincipalKind,
    pub groups: BTreeSet<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct VerifiedOperatorIdentity {
    pub principal: OperatorPrincipal,
    pub username: Option<String>,
    pub authorized_party: Option<String>,
    pub authenticated_via_credential: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct LocalAzureCliProfile {
    pub oid: String,
    pub username: String,
    pub name: Option<String>,
    pub roles: Vec<String>,
    pub source: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum AuthError {
    Unauthenticated(String),
    Forbidden(String),
}

impl AuthError {
    #[must_use]
    pub const fn status_code(&self) -> u16 {
        match self {
            Self::Unauthenticated(_) => 401,
            Self::Forbidden(_) => 403,
        }
    }

    #[must_use]
    pub fn message(&self) -> &str {
        match self {
            Self::Unauthenticated(m) | Self::Forbidden(m) => m,
        }
    }
}

#[derive(Clone, Debug, Deserialize)]
struct JwtHeader {
    alg: String,
    #[serde(default)]
    kid: Option<String>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct JwkRsaKey {
    #[serde(default)]
    pub kty: String,
    #[serde(default)]
    pub kid: Option<String>,
    #[serde(default)]
    pub n: Option<String>,
    #[serde(default)]
    pub e: Option<String>,
}

#[derive(Clone, Debug, Deserialize)]
struct JwksDocument {
    keys: Vec<JwkRsaKey>,
}

#[derive(Clone, Debug)]
struct CachedJwks {
    fetched_at: Instant,
    keys: Vec<JwkRsaKey>,
}

#[derive(Clone, Debug)]
pub struct EntraJwtConfig {
    pub tenant_id: String,
    pub audience: String,
    pub issuer: String,
    pub jwks_uri: String,
    pub group_ids: BTreeMap<OperatorRole, String>,
    pub static_jwks_json: Option<String>,
}

#[derive(Clone, Debug)]
pub enum AuthMode {
    EntraJwt(EntraJwtConfig),
    LocalAzureCli {
        profile: LocalAzureCliProfile,
        principal: OperatorPrincipal,
        session_token: String,
    },
    StaticTestBearer {
        expected_token: String,
    },
    DevMode,
    FailClosedUnconfigured,
}

#[derive(Clone)]
pub struct OperatorAuthenticator {
    mode: AuthMode,
    jwks_cache: Arc<RwLock<Option<CachedJwks>>>,
    jwks_refresh_lock: Arc<Mutex<()>>,
}

impl OperatorAuthenticator {
    #[must_use]
    pub fn new(mode: AuthMode) -> Self {
        Self {
            mode,
            jwks_cache: Arc::new(RwLock::new(None)),
            jwks_refresh_lock: Arc::new(Mutex::new(())),
        }
    }

    pub fn from_env() -> Result<Self, String> {
        let env_map: BTreeMap<String, String> = env::vars().collect();
        Self::from_env_map(&env_map, None)
    }

    pub fn from_env_map(
        env_map: &BTreeMap<String, String>,
        az_override: Option<(&str, &str)>,
    ) -> Result<Self, String> {
        let dev_mode = parse_bool_env(env_map, "FDAI_OPERATOR_API_DEV_MODE");
        let local_cli = parse_bool_env(env_map, "FDAI_OPERATOR_API_LOCAL_AZURE_CLI");
        let local_cli_confirm = parse_bool_env(env_map, "FDAI_OPERATOR_API_LOCAL_AZURE_CLI_CONFIRM");
        let local_entra = parse_bool_env(env_map, "FDAI_OPERATOR_API_LOCAL_ENTRA");
        let runtime_env = env_map
            .get("RUNTIME_ENV")
            .map(|s| s.trim().to_ascii_lowercase())
            .unwrap_or_default();

        if local_cli != local_cli_confirm {
            return Err(String::from(
                "FDAI_OPERATOR_API_LOCAL_AZURE_CLI and FDAI_OPERATOR_API_LOCAL_AZURE_CLI_CONFIRM MUST be enabled together",
            ));
        }
        if local_cli {
            if runtime_env != "dev" {
                return Err(String::from(
                    "FDAI_OPERATOR_API_LOCAL_AZURE_CLI requires RUNTIME_ENV=dev",
                ));
            }
            if dev_mode || local_entra {
                return Err(String::from(
                    "FDAI_OPERATOR_API_LOCAL_AZURE_CLI MUST NOT be combined with DEV_MODE or LOCAL_ENTRA",
                ));
            }
            let (profile, principal) = resolve_local_azure_cli_identity(az_override)?;
            let session_token = generate_csprng_hex_token(32)?;
            return Ok(Self::new(AuthMode::LocalAzureCli {
                profile,
                principal,
                session_token,
            }));
        }

        if let Some(bearer) = non_empty(env_map, "FDAI_E2E_BEARER") {
            return Ok(Self::new(AuthMode::StaticTestBearer {
                expected_token: bearer,
            }));
        }

        if dev_mode {
            return Ok(Self::new(AuthMode::DevMode));
        }

        let tenant = non_empty(env_map, "FDAI_ENTRA_TENANT_ID");
        let audience = non_empty(env_map, "FDAI_API_AUDIENCE");
        if let (Some(tenant_id), Some(aud)) = (tenant, audience) {
            let issuer = non_empty(env_map, "FDAI_ENTRA_ISSUER")
                .unwrap_or_else(|| format!("https://login.microsoftonline.com/{tenant_id}/v2.0"));
            let jwks_uri = non_empty(env_map, "FDAI_ENTRA_JWKS_URI").unwrap_or_else(|| {
                format!("https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys")
            });
            let mut group_ids = BTreeMap::new();
            for (role, key) in [
                (OperatorRole::Reader, "FDAI_RBAC_READERS_GROUP_ID"),
                (OperatorRole::Contributor, "FDAI_RBAC_CONTRIBUTORS_GROUP_ID"),
                (OperatorRole::Approver, "FDAI_RBAC_APPROVERS_GROUP_ID"),
                (OperatorRole::Owner, "FDAI_RBAC_OWNERS_GROUP_ID"),
                (OperatorRole::BreakGlass, "FDAI_RBAC_BREAK_GLASS_GROUP_ID"),
            ] {
                if let Some(gid) = non_empty(env_map, key) {
                    if group_ids.values().any(|existing| existing == &gid) {
                        return Err(String::from("Operator RBAC group IDs MUST be unique"));
                    }
                    group_ids.insert(role, gid);
                }
            }
            let static_jwks_json = non_empty(env_map, "FDAI_ENTRA_STATIC_JWKS_JSON");
            return Ok(Self::new(AuthMode::EntraJwt(EntraJwtConfig {
                tenant_id,
                audience: aud,
                issuer,
                jwks_uri,
                group_ids,
                static_jwks_json,
            })));
        }

        Ok(Self::new(AuthMode::FailClosedUnconfigured))
    }

    #[must_use]
    pub const fn mode_label(&self) -> &'static str {
        match self.mode {
            AuthMode::EntraJwt(_) => "entra-jwt-rs256",
            AuthMode::LocalAzureCli { .. } => "local-azure-cli",
            AuthMode::StaticTestBearer { .. } => "static-test-bearer",
            AuthMode::DevMode => "dev-mode",
            AuthMode::FailClosedUnconfigured => "fail-closed-unconfigured",
        }
    }

    #[must_use]
    pub const fn is_local_azure_cli(&self) -> bool {
        matches!(self.mode, AuthMode::LocalAzureCli { .. })
    }

    #[must_use]
    pub fn local_cli_profile_and_token(&self) -> Option<(&LocalAzureCliProfile, &str)> {
        if let AuthMode::LocalAzureCli {
            profile,
            session_token,
            ..
        } = &self.mode
        {
            Some((profile, session_token.as_str()))
        } else {
            None
        }
    }

    pub async fn authenticate(
        &self,
        authorization_header: Option<&str>,
    ) -> Result<VerifiedOperatorIdentity, AuthError> {
        match &self.mode {
            AuthMode::DevMode => {
                let roles = READER_ROLES.into_iter().collect();
                Ok(VerifiedOperatorIdentity {
                    principal: OperatorPrincipal {
                        subject_id: String::from("dev-anonymous-operator"),
                        roles,
                        principal_kind: OperatorPrincipalKind::Human,
                        groups: BTreeSet::new(),
                    },
                    username: Some(String::from("dev-operator@local")),
                    authorized_party: None,
                    authenticated_via_credential: false,
                })
            }
            AuthMode::FailClosedUnconfigured => Err(AuthError::Unauthenticated(String::from(
                "Entra authentication is required (configure FDAI_ENTRA_TENANT_ID + FDAI_API_AUDIENCE or FDAI_OPERATOR_API_DEV_MODE=1)",
            ))),
            AuthMode::LocalAzureCli {
                profile,
                principal,
                session_token,
            } => {
                let expected = format!("{BEARER_PREFIX}{session_token}");
                let provided = authorization_header.unwrap_or("");
                if constant_time_eq_str(provided, &expected) {
                    Ok(VerifiedOperatorIdentity {
                        principal: principal.clone(),
                        username: Some(profile.username.clone()),
                        authorized_party: None,
                        authenticated_via_credential: true,
                    })
                } else {
                    Err(AuthError::Unauthenticated(String::from(
                        "local Azure CLI session token is missing or invalid",
                    )))
                }
            }
            AuthMode::StaticTestBearer { expected_token } => {
                let token = extract_bearer(authorization_header)?;
                if !constant_time_eq_str(token, expected_token) {
                    return Err(AuthError::Unauthenticated(String::from(
                        "invalid bearer token",
                    )));
                }
                Ok(VerifiedOperatorIdentity {
                    principal: OperatorPrincipal {
                        subject_id: String::from("live-e2e-operator"),
                        roles: READER_ROLES.into_iter().collect(),
                        principal_kind: OperatorPrincipalKind::Human,
                        groups: BTreeSet::new(),
                    },
                    username: Some(String::from("live-e2e@local")),
                    authorized_party: None,
                    authenticated_via_credential: true,
                })
            }
            AuthMode::EntraJwt(cfg) => {
                let token = extract_bearer(authorization_header)?;
                let now_epoch = unix_now_secs();
                let header = decode_jwt_header(token)?;
                if header.alg != "RS256" {
                    return Err(AuthError::Unauthenticated(String::from(
                        "Entra token verification failed: unsupported alg (RS256 required)",
                    )));
                }
                let (keys, from_cache) = self.load_jwks_keys(cfg, header.kid.as_deref(), false).await?;
                match verify_entra_jwt_with_keys(token, &keys, cfg, now_epoch) {
                    Ok(id) => Ok(id),
                    Err(first_err) if from_cache && cfg.static_jwks_json.is_none() => {
                        let (fresh_keys, _) =
                            self.load_jwks_keys(cfg, header.kid.as_deref(), true).await?;
                        verify_entra_jwt_with_keys(token, &fresh_keys, cfg, now_epoch)
                            .map_err(|_| first_err)
                    }
                    Err(err) => Err(err),
                }
            }
        }
    }

    pub async fn require_any(
        &self,
        authorization_header: Option<&str>,
        required: &[OperatorRole],
    ) -> Result<VerifiedOperatorIdentity, AuthError> {
        let identity = self.authenticate(authorization_header).await?;
        if !required
            .iter()
            .any(|role| identity.principal.roles.contains(role))
        {
            let expected: Vec<&str> = required.iter().map(|r| r.as_str()).collect();
            let actual: Vec<&str> = identity.principal.roles.iter().map(|r| r.as_str()).collect();
            return Err(AuthError::Forbidden(format!(
                "principal lacks required role: any of {{{}}} (has {{{}}})",
                expected.join(", "),
                actual.join(", ")
            )));
        }
        Ok(identity)
    }

    pub fn enforce_min_rank(
        identity: &VerifiedOperatorIdentity,
        min_role: OperatorRole,
    ) -> Result<(), AuthError> {
        let highest = identity
            .principal
            .roles
            .iter()
            .map(|r| r.rank())
            .max()
            .unwrap_or(-1);
        if highest < min_role.rank() {
            return Err(AuthError::Forbidden(format!(
                "principal role does not meet required floor ({})",
                min_role.as_str()
            )));
        }
        Ok(())
    }

    async fn load_jwks_keys(
        &self,
        cfg: &EntraJwtConfig,
        kid: Option<&str>,
        force_refresh: bool,
    ) -> Result<(Vec<JwkRsaKey>, bool), AuthError> {
        if let Some(ref static_json) = cfg.static_jwks_json {
            let doc: JwksDocument = serde_json::from_str(static_json).map_err(|_| {
                AuthError::Unauthenticated(String::from("Entra token verification failed: invalid JWKS"))
            })?;
            return Ok((doc.keys, false));
        }
        if !force_refresh {
            let guard = self.jwks_cache.read().await;
            if let Some(ref cached) = *guard {
                let fresh = cached.fetched_at.elapsed() < JWKS_CACHE_TTL;
                let has_kid = kid.is_none_or(|k| {
                    cached.keys.iter().any(|j| j.kid.as_deref() == Some(k))
                });
                if fresh && has_kid {
                    return Ok((cached.keys.clone(), true));
                }
            }
        }
        let _sf_guard = self.jwks_refresh_lock.lock().await;
        if !force_refresh {
            let guard = self.jwks_cache.read().await;
            if let Some(ref cached) = *guard {
                let fresh = cached.fetched_at.elapsed() < JWKS_CACHE_TTL;
                let has_kid = kid.is_none_or(|k| {
                    cached.keys.iter().any(|j| j.kid.as_deref() == Some(k))
                });
                if fresh && has_kid {
                    return Ok((cached.keys.clone(), true));
                }
            }
        }
        let fetched = fetch_jwks_document(&cfg.jwks_uri).await?;
        {
            let mut guard = self.jwks_cache.write().await;
            *guard = Some(CachedJwks {
                fetched_at: Instant::now(),
                keys: fetched.clone(),
            });
        }
        Ok((fetched, false))
    }
}

pub fn check_loopback_and_origin(
    remote_ip: IpAddr,
    origin_header: Option<&str>,
    allowed_origins: &[String],
) -> Result<(), AuthError> {
    if !remote_ip.is_loopback() {
        return Err(AuthError::Forbidden(String::from(
            "local Azure CLI authentication requires a loopback client",
        )));
    }
    if let Some(origin) = origin_header {
        if !allowed_origins.iter().any(|o| o == origin) {
            return Err(AuthError::Forbidden(String::from(
                "local Azure CLI authentication rejected the request origin",
            )));
        }
    }
    Ok(())
}

fn decode_jwt_header(token: &str) -> Result<JwtHeader, AuthError> {
    let header_b64 = token.split('.').next().unwrap_or("");
    let header_bytes = URL_SAFE_NO_PAD.decode(header_b64).map_err(|_| {
        AuthError::Unauthenticated(String::from("Entra token verification failed: malformed header"))
    })?;
    serde_json::from_slice(&header_bytes).map_err(|_| {
        AuthError::Unauthenticated(String::from("Entra token verification failed: invalid header JSON"))
    })
}

pub fn verify_entra_jwt_with_keys(
    token: &str,
    keys: &[JwkRsaKey],
    cfg: &EntraJwtConfig,
    now_epoch: i64,
) -> Result<VerifiedOperatorIdentity, AuthError> {
    let mut parts = token.split('.');
    let (Some(h_b64), Some(p_b64), Some(s_b64), None) =
        (parts.next(), parts.next(), parts.next(), parts.next())
    else {
        return Err(AuthError::Unauthenticated(String::from(
            "Entra token verification failed: token must contain 3 JWT segments",
        )));
    };
    let header = decode_jwt_header(token)?;
    if header.alg != "RS256" {
        return Err(AuthError::Unauthenticated(String::from(
            "Entra token verification failed: RS256 required",
        )));
    }
    let sig_bytes = URL_SAFE_NO_PAD.decode(s_b64).map_err(|_| {
        AuthError::Unauthenticated(String::from("Entra token verification failed: invalid signature encoding"))
    })?;
    let signing_input = format!("{h_b64}.{p_b64}");

    let candidates: Vec<&JwkRsaKey> = keys
        .iter()
        .filter(|k| {
            k.kty == "RSA"
                && header
                    .kid
                    .as_deref()
                    .is_none_or(|wanted| k.kid.as_deref() == Some(wanted))
        })
        .collect();
    if candidates.is_empty() {
        return Err(AuthError::Unauthenticated(String::from(
            "Entra token verification failed: no matching RSA signing key",
        )));
    }

    let mut sig_valid = false;
    for jwk in candidates {
        let (Some(n_b64), Some(e_b64)) = (jwk.n.as_deref(), jwk.e.as_deref()) else {
            continue;
        };
        let (Ok(n_bytes), Ok(e_bytes)) = (URL_SAFE_NO_PAD.decode(n_b64), URL_SAFE_NO_PAD.decode(e_b64)) else {
            continue;
        };
        let pubkey = RsaPublicKeyComponents {
            n: n_bytes.as_slice(),
            e: e_bytes.as_slice(),
        };
        if pubkey
            .verify(&RSA_PKCS1_2048_8192_SHA256, signing_input.as_bytes(), &sig_bytes)
            .is_ok()
        {
            sig_valid = true;
            break;
        }
    }
    if !sig_valid {
        return Err(AuthError::Unauthenticated(String::from(
            "Entra token verification failed: InvalidSignatureError",
        )));
    }

    let payload_bytes = URL_SAFE_NO_PAD.decode(p_b64).map_err(|_| {
        AuthError::Unauthenticated(String::from("Entra token verification failed: malformed payload"))
    })?;
    let claims: Value = serde_json::from_slice(&payload_bytes).map_err(|_| {
        AuthError::Unauthenticated(String::from("Entra token verification failed: invalid payload JSON"))
    })?;

    validate_time_iss_aud(&claims, cfg, now_epoch)?;
    build_verified_identity_from_claims(&claims, &cfg.group_ids)
}

fn audience_matches_entra(claim_aud: &str, expected_aud: &str) -> bool {
    if claim_aud == expected_aud {
        return true;
    }
    let norm_claim = claim_aud.strip_prefix("api://").unwrap_or(claim_aud);
    let norm_expected = expected_aud.strip_prefix("api://").unwrap_or(expected_aud);
    !norm_expected.is_empty() && norm_claim == norm_expected
}

fn issuer_matches_entra(claim_iss: &str, cfg: &EntraJwtConfig) -> bool {
    if claim_iss == cfg.issuer {
        return true;
    }
    if cfg.tenant_id.is_empty() {
        return false;
    }
    let v2 = format!("https://login.microsoftonline.com/{}/v2.0", cfg.tenant_id);
    let v1 = format!("https://sts.windows.net/{}/", cfg.tenant_id);
    claim_iss == v2 || claim_iss == v1
}

fn validate_time_iss_aud(
    claims: &Value,
    cfg: &EntraJwtConfig,
    now_epoch: i64,
) -> Result<(), AuthError> {
    let exp = claims.get("exp").and_then(Value::as_i64).ok_or_else(|| {
        AuthError::Unauthenticated(String::from("Entra token verification failed: missing exp"))
    })?;
    if now_epoch > exp + JWT_LEEWAY_SECS {
        return Err(AuthError::Unauthenticated(String::from(
            "Entra token verification failed: ExpiredSignatureError",
        )));
    }
    if let Some(nbf) = claims.get("nbf").and_then(Value::as_i64) {
        if now_epoch + JWT_LEEWAY_SECS < nbf {
            return Err(AuthError::Unauthenticated(String::from(
                "Entra token verification failed: ImmatureSignatureError",
            )));
        }
    }
    let iss = claims.get("iss").and_then(Value::as_str).unwrap_or("");
    if !issuer_matches_entra(iss, cfg) {
        return Err(AuthError::Unauthenticated(String::from(
            "Entra token verification failed: InvalidIssuerError",
        )));
    }
    let aud_matches = match claims.get("aud") {
        Some(Value::String(s)) => audience_matches_entra(s, &cfg.audience),
        Some(Value::Array(arr)) => arr
            .iter()
            .any(|v| v.as_str().is_some_and(|s| audience_matches_entra(s, &cfg.audience))),
        _ => false,
    };
    if !aud_matches {
        return Err(AuthError::Unauthenticated(String::from(
            "Entra token verification failed: InvalidAudienceError",
        )));
    }
    Ok(())
}

fn build_verified_identity_from_claims(
    claims: &Value,
    group_ids: &BTreeMap<OperatorRole, String>,
) -> Result<VerifiedOperatorIdentity, AuthError> {
    let oid = claims
        .get("oid")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| AuthError::Unauthenticated(String::from("invalid claims: missing non-empty oid")))?;

    if claims.get("hasgroups").and_then(Value::as_bool) == Some(true)
        || claims
            .get("_claim_names")
            .and_then(Value::as_object)
            .is_some_and(|m| m.contains_key("groups"))
    {
        return Err(AuthError::Unauthenticated(String::from(
            "invalid claims: group overage cannot establish exact groups",
        )));
    }

    let groups = parse_groups_claim(claims.get("groups"))?;
    let mut roles = parse_roles_claim(claims.get("roles"));
    let kind = classify_principal_kind(claims)?;
    let azp = parse_authorized_party(claims)?;

    if kind == OperatorPrincipalKind::Workload {
        if roles.len() != 1 || !roles.contains(&OperatorRole::Reader) {
            return Err(AuthError::Unauthenticated(String::from(
                "invalid claims: workload principals require the Reader App Role",
            )));
        }
        if !groups.is_empty() {
            return Err(AuthError::Unauthenticated(String::from(
                "invalid claims: workload principals MUST NOT carry group claims",
            )));
        }
        return Ok(VerifiedOperatorIdentity {
            principal: OperatorPrincipal {
                subject_id: sha256_prefixed_lower(oid),
                roles,
                principal_kind: OperatorPrincipalKind::Workload,
                groups: BTreeSet::new(),
            },
            username: None,
            authorized_party: azp,
            authenticated_via_credential: true,
        });
    }

    if roles.is_empty() {
        for (role, gid) in group_ids {
            if groups.contains(gid) {
                roles.insert(*role);
            }
        }
    }

    let username = ["email", "preferred_username", "upn"].iter().find_map(|k| {
        claims
            .get(*k)
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|s| !s.is_empty() && s.len() <= 320 && !s.contains('\0'))
            .map(String::from)
    });

    Ok(VerifiedOperatorIdentity {
        principal: OperatorPrincipal {
            subject_id: oid.to_string(),
            roles,
            principal_kind: OperatorPrincipalKind::Human,
            groups,
        },
        username,
        authorized_party: azp,
        authenticated_via_credential: true,
    })
}

fn parse_roles_claim(raw: Option<&Value>) -> BTreeSet<OperatorRole> {
    let mut out = BTreeSet::new();
    match raw {
        Some(Value::String(s)) => {
            for tok in s.split_whitespace() {
                if let Some(r) = OperatorRole::parse_str(tok) {
                    out.insert(r);
                }
            }
        }
        Some(Value::Array(arr)) => {
            for v in arr {
                if let Some(s) = v.as_str() {
                    if let Some(r) = OperatorRole::parse_str(s) {
                        out.insert(r);
                    }
                }
            }
        }
        _ => {}
    }
    out
}

fn parse_groups_claim(raw: Option<&Value>) -> Result<BTreeSet<String>, AuthError> {
    let Some(val) = raw else {
        return Ok(BTreeSet::new());
    };
    if val.is_null() {
        return Ok(BTreeSet::new());
    }
    let Some(arr) = val.as_array() else {
        return Err(AuthError::Unauthenticated(String::from(
            "invalid claims: groups must be an array",
        )));
    };
    if arr.len() > 64 {
        return Err(AuthError::Unauthenticated(String::from(
            "invalid claims: groups exceed bounds",
        )));
    }
    let mut set = BTreeSet::new();
    for item in arr {
        let Some(s) = item.as_str() else {
            return Err(AuthError::Unauthenticated(String::from(
                "invalid claims: groups contain a malformed value",
            )));
        };
        if s.trim().is_empty() || s.len() > 256 || !set.insert(s.to_string()) {
            return Err(AuthError::Unauthenticated(String::from(
                "invalid claims: groups contain duplicate or malformed value",
            )));
        }
    }
    Ok(set)
}

fn classify_principal_kind(claims: &Value) -> Result<OperatorPrincipalKind, AuthError> {
    match claims.get("idtyp").and_then(Value::as_str) {
        Some("user") => Ok(OperatorPrincipalKind::Human),
        Some("app") => Ok(OperatorPrincipalKind::Workload),
        None => {
            if claims
                .get("scp")
                .and_then(Value::as_str)
                .is_some_and(|s| !s.trim().is_empty())
            {
                Ok(OperatorPrincipalKind::Human)
            } else {
                Err(AuthError::Unauthenticated(String::from(
                    "invalid claims: missing principal type",
                )))
            }
        }
        Some(_) => Err(AuthError::Unauthenticated(String::from(
            "invalid claims: unsupported principal type",
        ))),
    }
}

fn parse_authorized_party(claims: &Value) -> Result<Option<String>, AuthError> {
    let raw = claims.get("azp").or_else(|| claims.get("appid"));
    let Some(val) = raw else {
        return Ok(None);
    };
    if val.is_null() {
        return Ok(None);
    }
    let Some(s) = val.as_str() else {
        return Err(AuthError::Unauthenticated(String::from(
            "invalid claims: authorized party is malformed",
        )));
    };
    let trimmed = s.trim();
    if trimmed.is_empty() || trimmed.len() > 200 {
        return Err(AuthError::Unauthenticated(String::from(
            "invalid claims: authorized party is malformed",
        )));
    }
    Ok(Some(trimmed.to_string()))
}

fn resolve_local_azure_cli_identity(
    az_override: Option<(&str, &str)>,
) -> Result<(LocalAzureCliProfile, OperatorPrincipal), String> {
    let (acct_raw, tok_raw) = if let Some((a, t)) = az_override {
        (a.to_string(), t.to_string())
    } else {
        let a = run_az_cli(&["account", "show", "--output", "json"])?;
        let t = run_az_cli(&[
            "account",
            "get-access-token",
            "--resource",
            ARM_RESOURCE,
            "--output",
            "json",
        ])?;
        (a, t)
    };
    let acct: Value = serde_json::from_str(&acct_raw)
        .map_err(|_| String::from("Azure CLI returned invalid account JSON"))?;
    if acct.get("state").and_then(Value::as_str) != Some("Enabled") {
        return Err(String::from("the active Azure subscription is not enabled"));
    }
    let user = acct
        .get("user")
        .and_then(Value::as_object)
        .ok_or_else(|| String::from("local Azure CLI auth requires an interactive user login"))?;
    if user.get("type").and_then(Value::as_str) != Some("user") {
        return Err(String::from("local Azure CLI auth requires an interactive user login"));
    }

    let tok_doc: Value = serde_json::from_str(&tok_raw)
        .map_err(|_| String::from("Azure CLI returned invalid access token JSON"))?;
    let access_token = tok_doc
        .get("accessToken")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| String::from("Azure CLI returned no access token; run 'az login'"))?;
    let payload_b64 = access_token
        .split('.')
        .nth(1)
        .ok_or_else(|| String::from("Azure CLI returned a malformed access token"))?;
    let payload_bytes = URL_SAFE_NO_PAD
        .decode(payload_b64)
        .map_err(|_| String::from("Azure CLI returned a malformed access token"))?;
    let claims: Value = serde_json::from_slice(&payload_bytes)
        .map_err(|_| String::from("Azure CLI returned a malformed access token"))?;

    let acct_tid = acct.get("tenantId").and_then(Value::as_str).unwrap_or("");
    let tok_tid = claims.get("tid").and_then(Value::as_str).unwrap_or("");
    if acct_tid.is_empty() || acct_tid != tok_tid {
        return Err(String::from(
            "Azure CLI account and access-token tenants do not match",
        ));
    }
    let oid = claims
        .get("oid")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| String::from("Azure CLI user token has no stable Entra object id"))?;
    let username = claims
        .get("preferred_username")
        .or_else(|| claims.get("upn"))
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .or_else(|| user.get("name").and_then(Value::as_str).filter(|s| !s.is_empty()))
        .ok_or_else(|| String::from("Azure CLI user has no displayable username"))?;
    let name = claims
        .get("name")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .map(String::from);

    let mut roles = BTreeSet::new();
    roles.insert(OperatorRole::Contributor);
    let profile = LocalAzureCliProfile {
        oid: oid.to_string(),
        username: username.to_string(),
        name,
        roles: vec![String::from("contributor")],
        source: String::from("azure-cli"),
    };
    let principal = OperatorPrincipal {
        subject_id: oid.to_string(),
        roles,
        principal_kind: OperatorPrincipalKind::Human,
        groups: BTreeSet::new(),
    };
    Ok((profile, principal))
}

fn run_az_cli(args: &[&str]) -> Result<String, String> {
    let mut child = Command::new("az")
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|_| String::from("could not read the local Azure CLI session; install Azure CLI and run 'az login'"))?;
    let started = Instant::now();
    loop {
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) => {
                if started.elapsed() >= AZ_CLI_TIMEOUT {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(String::from("Azure CLI session lookup timed out after 20s"));
                }
                std::thread::sleep(Duration::from_millis(25));
            }
            Err(_) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(String::from("could not wait on Azure CLI process"));
            }
        }
    }
    let out = child
        .wait_with_output()
        .map_err(|_| String::from("could not read Azure CLI output"))?;
    if !out.status.success() {
        return Err(String::from(
            "could not read the local Azure CLI session; run 'az login'",
        ));
    }
    String::from_utf8(out.stdout).map_err(|_| String::from("Azure CLI returned non-UTF-8 output"))
}

pub fn validate_jwks_uri_scheme(jwks_uri: &str) -> Result<(), AuthError> {
    let lower = jwks_uri.trim().to_ascii_lowercase();
    let is_loopback_http = lower.starts_with("http://127.0.0.1:")
        || lower.starts_with("http://[::1]:")
        || lower.starts_with("http://localhost:");
    if lower.starts_with("https://") || is_loopback_http {
        Ok(())
    } else {
        Err(AuthError::Unauthenticated(String::from(
            "Entra JWKS URI MUST use https:// (plain http only permitted on loopback)",
        )))
    }
}

async fn fetch_jwks_document(jwks_uri: &str) -> Result<Vec<JwkRsaKey>, AuthError> {
    validate_jwks_uri_scheme(jwks_uri)?;
    let https = HttpsConnectorBuilder::new()
        .with_webpki_roots()
        .https_or_http()
        .enable_http1()
        .build();
    let client = Client::builder(TokioExecutor::new()).build::<_, String>(https);
    let req = Request::builder()
        .method("GET")
        .uri(jwks_uri)
        .header("accept", "application/json")
        .body(String::new())
        .map_err(|_| AuthError::Unauthenticated(String::from("Entra JWKS URI is invalid")))?;
    let resp = tokio::time::timeout(JWKS_FETCH_TIMEOUT, client.request(req))
        .await
        .map_err(|_| AuthError::Unauthenticated(String::from("Entra JWKS fetch timed out")))?
        .map_err(|_| AuthError::Unauthenticated(String::from("Entra JWKS fetch failed")))?;
    if !resp.status().is_success() {
        return Err(AuthError::Unauthenticated(String::from(
            "Entra JWKS endpoint returned error status",
        )));
    }
    let collected = tokio::time::timeout(JWKS_FETCH_TIMEOUT, resp.into_body().collect())
        .await
        .map_err(|_| AuthError::Unauthenticated(String::from("Entra JWKS read timed out")))?
        .map_err(|_| AuthError::Unauthenticated(String::from("Entra JWKS read failed")))?
        .to_bytes();
    if collected.len() > MAX_JWKS_BYTES {
        return Err(AuthError::Unauthenticated(String::from(
            "Entra JWKS payload exceeds limit",
        )));
    }
    let doc: JwksDocument = serde_json::from_slice(&collected)
        .map_err(|_| AuthError::Unauthenticated(String::from("Entra JWKS JSON is invalid")))?;
    Ok(doc.keys)
}

fn extract_bearer(header: Option<&str>) -> Result<&str, AuthError> {
    let raw = header.ok_or_else(|| AuthError::Unauthenticated(String::from("Authorization header missing")))?;
    if raw.len() > MAX_AUTH_HEADER_BYTES {
        return Err(AuthError::Unauthenticated(String::from(
            "Authorization header exceeds maximum bounded length",
        )));
    }
    let rest = raw.strip_prefix(BEARER_PREFIX).ok_or_else(|| {
        AuthError::Unauthenticated(String::from("Authorization header MUST use the Bearer scheme"))
    })?;
    let token = rest.trim();
    if token.is_empty() {
        return Err(AuthError::Unauthenticated(String::from("Bearer token is empty")));
    }
    Ok(token)
}

fn constant_time_eq_str(a: &str, b: &str) -> bool {
    if a.len() != b.len() {
        return false;
    }
    bool::from(a.as_bytes().ct_eq(b.as_bytes()))
}

fn generate_csprng_hex_token(num_bytes: usize) -> Result<String, String> {
    let mut buf = vec![0_u8; num_bytes];
    SystemRandom::new()
        .fill(&mut buf)
        .map_err(|_| String::from("CSPRNG failed while generating local session token"))?;
    let mut hex = String::with_capacity(num_bytes * 2);
    for b in buf {
        let _ = write!(hex, "{b:02x}");
    }
    Ok(hex)
}

fn sha256_prefixed_lower(input: &str) -> String {
    let lower = input.to_lowercase();
    let d = digest(&SHA256, lower.as_bytes());
    let mut out = String::from("sha256:");
    for b in d.as_ref() {
        let _ = write!(out, "{b:02x}");
    }
    out
}

fn parse_bool_env(map: &BTreeMap<String, String>, key: &str) -> bool {
    map.get(key)
        .is_some_and(|v| matches!(v.trim().to_ascii_lowercase().as_str(), "1" | "true" | "yes"))
}

fn non_empty(map: &BTreeMap<String, String>, key: &str) -> Option<String> {
    map.get(key)
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
}

fn unix_now_secs() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0_i64, |d| d.as_secs() as i64)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fail_closed_by_default_and_local_cli_enforces_token_and_loopback() {
        let empty = BTreeMap::new();
        let auth = OperatorAuthenticator::from_env_map(&empty, None);
        assert!(auth.is_ok());
        if let Ok(a) = auth {
            assert_eq!(a.mode_label(), "fail-closed-unconfigured");
        }

        let mut bad_cli = BTreeMap::new();
        bad_cli.insert(String::from("FDAI_OPERATOR_API_LOCAL_AZURE_CLI"), String::from("1"));
        assert!(OperatorAuthenticator::from_env_map(&bad_cli, None).is_err());

        let mut ok_cli = BTreeMap::new();
        ok_cli.insert(String::from("RUNTIME_ENV"), String::from("dev"));
        ok_cli.insert(String::from("FDAI_OPERATOR_API_LOCAL_AZURE_CLI"), String::from("1"));
        ok_cli.insert(String::from("FDAI_OPERATOR_API_LOCAL_AZURE_CLI_CONFIRM"), String::from("1"));
        let acct = r#"{"state":"Enabled","tenantId":"t-1","user":{"type":"user","name":"op@contoso.com"}}"#;
        let payload = URL_SAFE_NO_PAD.encode(r#"{"tid":"t-1","oid":"oid-123","preferred_username":"op@contoso.com","name":"Local Op"}"#);
        let tok_json = format!(r#"{{"accessToken":"hdr.{payload}.sig"}}"#);
        let cli_auth = OperatorAuthenticator::from_env_map(&ok_cli, Some((acct, &tok_json)));
        assert!(cli_auth.is_ok());
        if let Ok(a) = cli_auth {
            assert_eq!(a.mode_label(), "local-azure-cli");
            assert!(a.local_cli_profile_and_token().is_some());
        }
    }

    #[test]
    fn claims_enforces_group_overage_workload_and_rbac_mapping() {
        let mut gmap = BTreeMap::new();
        gmap.insert(OperatorRole::Approver, String::from("grp-approvers"));
        let overage = serde_json::json!({"oid":"u1","idtyp":"user","hasgroups":true});
        assert!(build_verified_identity_from_claims(&overage, &gmap).is_err());

        let bad_workload = serde_json::json!({"oid":"w1","idtyp":"app","roles":["owner"]});
        assert!(build_verified_identity_from_claims(&bad_workload, &gmap).is_err());

        let ok_workload = serde_json::json!({"oid":"w1","idtyp":"app","roles":["reader"]});
        let w = build_verified_identity_from_claims(&ok_workload, &gmap);
        assert!(w.is_ok());
        if let Ok(id) = w {
            assert!(id.principal.subject_id.starts_with("sha256:"));
            assert_eq!(id.principal.principal_kind, OperatorPrincipalKind::Workload);
        }

        let human = serde_json::json!({"oid":"u2","scp":"access","groups":["grp-approvers"],"preferred_username":"alice@contoso.com"});
        let h = build_verified_identity_from_claims(&human, &gmap);
        assert!(h.is_ok());
        if let Ok(id) = h {
            assert!(id.principal.roles.contains(&OperatorRole::Approver));
            assert_eq!(id.username.as_deref(), Some("alice@contoso.com"));
        }

        assert!(audience_matches_entra("382aeedf-6724-40d2-8ee8-591120f2dae5", "api://382aeedf-6724-40d2-8ee8-591120f2dae5"));
        assert!(audience_matches_entra("api://382aeedf-6724-40d2-8ee8-591120f2dae5", "382aeedf-6724-40d2-8ee8-591120f2dae5"));
        assert!(!audience_matches_entra("other-app-guid", "api://382aeedf-6724-40d2-8ee8-591120f2dae5"));
        let cfg = EntraJwtConfig {
            tenant_id: String::from("t-123"),
            audience: String::from("app-1"),
            issuer: String::from("https://login.microsoftonline.com/t-123/v2.0"),
            jwks_uri: String::from("https://login.microsoftonline.com/t-123/discovery/v2.0/keys"),
            group_ids: BTreeMap::new(),
            static_jwks_json: None,
        };
        assert!(issuer_matches_entra("https://login.microsoftonline.com/t-123/v2.0", &cfg));
        assert!(issuer_matches_entra("https://sts.windows.net/t-123/", &cfg));
        assert!(!issuer_matches_entra("https://sts.windows.net/other-tenant/", &cfg));
    }
}
