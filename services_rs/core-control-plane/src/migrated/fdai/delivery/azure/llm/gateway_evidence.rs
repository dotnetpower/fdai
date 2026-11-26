pub const SAFE_ID: &str = "^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$";
pub const CAPACITY_UNITS: &[&str] = &["tpm", "ptu", "gpu"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn record_gateway_route_evidence(mut response: String, mut target: String, mut model_role: String, mut sink: Option<String>) -> Result<(), &'static str> {
    let Some(mut sink) = sink.clone() else { return Err("APIM model route evidence has no durable sink"); };
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["record_gateway_route_evidence"];
