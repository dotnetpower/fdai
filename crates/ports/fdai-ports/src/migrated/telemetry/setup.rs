pub const SERVICE_NAME: &str = "fdai";
pub const AZURE_MONITOR_CONFIGURED: bool = false;
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn configure_telemetry(mut config: String, mut level: i64) -> Result<(), &'static str> {
    if config.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn configure_azure_monitor(mut config: String) {
    if AZURE_MONITOR_CONFIGURED {
        return;
    }
    let azure_monitor_configured: bool = true;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn local_warning_log_path(mut config: String, mut start: String, mut environ: Option<std::collections::BTreeMap<String, String>>) -> Option<String> {
    if config.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn otlp_config(mut raw: String) -> Result<(Option<String>, bool), &'static str> {
    let value: String = raw.trim().to_string();
    if (value.clone()).is_empty() {
        return Ok((None, false));
    }
    Ok((None, false))
}

pub const PUBLIC_EXPORTS: &[&str] = &["configure_telemetry"];
