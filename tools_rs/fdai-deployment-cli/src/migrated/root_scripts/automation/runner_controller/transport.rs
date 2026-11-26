use std::collections::BTreeMap;
pub const MAX_RESPONSE_BYTES: i64 = 4194304;
pub const TIMEOUT_SECONDS: i64 = 20;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HttpResponse {
    pub status: i64,
    pub data: String,
    pub headers: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProviderError {
    pub message: String,
}

impl ProviderError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ProviderError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ProviderError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NoRedirect {
    pub initialized: bool,
}

impl NoRedirect {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn redirect_request(&self, mut req: String, mut fp: String, mut code: i64, mut msg: String, mut headers: String, mut newurl: String) {
        if !self.initialized {
            return;
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Transport {
    pub initialized: bool,
}

impl Transport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn request(&self, mut method: String, mut url: String, mut headers: Option<std::collections::BTreeMap<String, String>>, mut body: String, mut accepted: Vec<i64>) -> Result<HttpResponse, &'static str> {
        let mut encoded: Option<String> = None;
        Ok(HttpResponse::default())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn reject_constant(mut value: String) -> Result<String, &'static str> {
    Err("Invalid JSON constant")
}

