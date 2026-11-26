#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn build_t1_mini_probe(mut container: String, mut environment: std::collections::BTreeMap<String, String>, mut identity: Option<String>, mut http_client: Option<String>, mut state_store: String, mut endpoint: Option<String>, mut endpoint_resolver: Option<String>) -> Result<Option<String>, &'static str> {
    let enabled_raw: String = (((environment.clone()).get("FDAI_T1_MINI_PROBE_ENABLED").cloned().unwrap_or_else(|| String::from("0"))).trim().to_string()).to_lowercase();
    if !(matches!(enabled_raw.as_str(), "0" | "1" | "false" | "true")) {
        return Err("FDAI_T1_MINI_PROBE_ENABLED MUST be 0 1 false or true");
    }
    let interval: i64 = ((environment.clone()).get("FDAI_NARRATOR_PROBE_INTERVAL_SECONDS").cloned().unwrap_or_else(|| String::from("300"))).trim().parse::<i64>().unwrap_or(0);
    if !(((30_i64) <= (interval)) && ((interval) <= (3600_i64))) {
        return Err("FDAI_NARRATOR_PROBE_INTERVAL_SECONDS MUST be in 30 3600");
    }
    Ok(None)
}

