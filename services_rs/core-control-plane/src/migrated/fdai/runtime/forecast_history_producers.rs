#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn build_forecast_history_producers(mut dsn: String, mut configuration: String, mut store: String) -> Result<Vec<String>, &'static str> {
    let mut producers: Vec<String> = Vec::<String>::new();
    Ok(producers.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["build_forecast_history_producers"];
