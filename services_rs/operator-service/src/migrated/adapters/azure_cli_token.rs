pub const AZURE_OPENAI_AUDIENCE: &str = "https://cognitiveservices.azure.com/";
pub const AZURE_CLI_TOKEN_TIMEOUT_SECONDS: f64 = 30.0;
pub const AZURE_CLI_KILL_WAIT_SECONDS: f64 = 5.0;
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn azure_cli_token(mut audience: String) -> Result<String, &'static str> {
    if audience.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["AZURE_CLI_KILL_WAIT_SECONDS", "AZURE_CLI_TOKEN_TIMEOUT_SECONDS", "AZURE_OPENAI_AUDIENCE", "azure_cli_token"];
