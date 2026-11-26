pub const DSN_ENV: &str = "FDAI_STATE_STORE_DSN";
pub trait ForecastEvidenceReader {
    fn health_snapshot(&self, now: String) -> std::collections::BTreeMap<String, String>;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn query_forecast_evidence(mut reader: String, mut observed_at: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::from([(String::from("observed_at"), String::new()), (String::from("snapshot"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn main() -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

