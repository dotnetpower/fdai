#[derive(Clone, Debug, Default, PartialEq)]
pub struct GovernedChaosProviderConfig {
    pub state_store_dsn: String,
    pub promotion_ledger_path: String,
    pub target_binding_id: String,
    pub approval_prefix: String,
    pub plan_prefix: String,
    pub dispatch_prefix: String,
    pub evidence_prefix: String,
    pub stop_event_prefix: String,
    pub statement_timeout_ms: i64,
    pub lock_timeout_ms: i64,
    pub connect_timeout_seconds: i64,
}

impl GovernedChaosProviderConfig {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_environment(mut environment: std::collections::BTreeMap<String, String>) -> GovernedChaosProviderConfig {
        if environment.is_empty() {
            return Default::default();
        }
        Default::default()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn required(mut environment: std::collections::BTreeMap<String, String>, mut name: String, mut max_length: i64) -> Result<String, &'static str> {
    let value: String = ((environment.clone()).get(name.as_str()).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn required_path(mut environment: std::collections::BTreeMap<String, String>, mut name: String) -> Result<String, &'static str> {
    let raw: String = required(environment.clone(), name.clone(), 4096_i64).unwrap_or_else(|_| String::new());
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn prefix(mut environment: std::collections::BTreeMap<String, String>, mut name: String) -> Result<String, &'static str> {
    let value: Option<String> = (environment.clone()).get(name.as_str()).cloned();
    if value.is_none() {
        let defaults: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("FDAI_GOVERNED_CHAOS_APPROVAL_PREFIX"), String::from("governed-chaos-approval:")), (String::from("FDAI_GOVERNED_CHAOS_PLAN_PREFIX"), String::from("governed-chaos-plan:")), (String::from("FDAI_GOVERNED_CHAOS_DISPATCH_PREFIX"), String::from("governed-chaos-dispatch:")), (String::from("FDAI_GOVERNED_CHAOS_EVIDENCE_PREFIX"), String::from("governed-chaos-recovery-evidence:")), (String::from("FDAI_GOVERNED_CHAOS_STOP_EVENT_PREFIX"), String::from("governed-chaos-stop-event:"))]);
    }
    Ok((value.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bounded_int(mut environment: std::collections::BTreeMap<String, String>, mut name: String, mut default: i64, mut minimum: i64, mut maximum: i64) -> Result<i64, &'static str> {
    let raw: Option<String> = (environment.clone()).get(name.as_str()).cloned();
    if (raw.is_none()) || ((raw.clone()) == Some(String::from(""))) {
        return Ok(default);
    }
    Ok(0_i64)
}

pub const PUBLIC_EXPORTS: &[&str] = &["GovernedChaosProviderConfig"];
