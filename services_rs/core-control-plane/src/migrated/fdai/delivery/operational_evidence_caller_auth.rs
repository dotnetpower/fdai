#[derive(Clone, Debug, Default, PartialEq)]
pub struct ValidatedCallerToken {
    pub issuer: String,
    pub audience: String,
    pub oid: String,
    pub expires_at: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StaticJwksBearerTokenValidator {
    pub issuer: String,
    pub audience: String,
    pub jwks_json: String,
    pub algorithms: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkloadCallerAuthenticator {
    pub expected_issuer: String,
    pub expected_audience: String,
    pub registered_producer_principal: String,
    pub validator: String,
}

pub const API_UUID_AUDIENCE: &str = "api://([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})";
pub const JWK_PUBLIC_FIELDS: &[&str] = &["kty", "use", "kid", "n", "e", "alg", "crv", "x", "y"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CallerAuthenticationError {
    pub message: String,
}

impl CallerAuthenticationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for CallerAuthenticationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CallerAuthenticationError {}

pub trait BearerTokenValidator {
    fn py_validate(&self, token: String) -> String;
}

impl StaticJwksBearerTokenValidator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn py_validate(&self, mut token: String) -> Result<ValidatedCallerToken, &'static str> {
        let accepted_audiences: Vec<String> = accepted_audiences(self.audience.clone());
        let jwks: String = load_jwks(self.jwks_json.clone()).unwrap_or_else(|_| String::new());
        Ok(ValidatedCallerToken::default())
    }
}

impl WorkloadCallerAuthenticator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn authenticate(&self, mut request: String) -> Option<String> {
        if request.is_empty() {
            return None;
        }
        None
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn accepted_audiences(mut expected: String) -> Vec<String> {
    if expected.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_jwks(mut raw: String) -> Result<String, &'static str> {
    if raw.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["BearerTokenValidator", "CallerAuthenticationError", "StaticJwksBearerTokenValidator", "ValidatedCallerToken", "WorkloadCallerAuthenticator"];
