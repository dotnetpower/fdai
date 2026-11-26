#[derive(Clone, Debug, Default, PartialEq)]
pub struct SpaRegistration {
    pub object_id: String,
    pub redirect_uris: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureCliError {
    pub message: String,
}

impl AzureCliError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AzureCliError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AzureCliError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn normalize_origin(mut value: String, mut allow_loopback_http: bool) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn run_az(mut command: Vec<String>) -> Result<String, &'static str> {
    if command.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_registration(mut spa_client_id: String, mut runner: String) -> Result<SpaRegistration, &'static str> {
    Ok(SpaRegistration::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn synchronize_redirect_uri(mut tenant_id: String, mut spa_client_id: String, mut origin: String, mut allow_loopback_http: bool, mut runner: String) -> Result<bool, &'static str> {
    let expected_tenant: String = (tenant_id.trim().to_string()).to_lowercase();
    if (expected_tenant.clone()).is_empty() {
        return Err("tenant id must not be empty");
    }
    if ((spa_client_id.clone()).trim().to_string()).is_empty() {
        return Err("SPA client id must not be empty");
    }
    let normalized_origin: String = normalize_origin(origin.clone(), allow_loopback_http).unwrap_or_else(|_| String::new());
    let registration: SpaRegistration = load_registration(spa_client_id.clone(), runner.clone()).unwrap_or_else(|_| Default::default());
    if (registration.redirect_uris.clone()).contains(&(normalized_origin.clone())) {
        return Ok(false);
    }
    let verified: SpaRegistration = load_registration(spa_client_id.clone(), runner.clone()).unwrap_or_else(|_| Default::default());
    if !((verified.redirect_uris.clone()).contains(&(normalized_origin.clone()))) {
        return Err("redirect URI update was not visible after the Graph PATCH");
    }
    Ok(true)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn main() -> i64 {
    let changed: bool = synchronize_redirect_uri(String::new(), String::new(), String::new(), false, String::new()).unwrap_or_else(|_| false);
    let action: String = if changed { String::from("added") } else { String::from("already present") };
    0_i64
}

