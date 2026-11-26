#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForecastHistoryBinding {
    pub kind: String,
    pub access_scope_digest: String,
    pub target_ref: String,
    pub state_type: String,
    pub to_states: Vec<String>,
    pub source_identity: String,
    pub source_revision: String,
    pub freshness_seconds: i64,
    pub active_states: Vec<String>,
    pub lookback_seconds: i64,
}

impl ForecastHistoryBinding {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "actions" | "changes" | "resource_lifecycle" | "excluded_windows") { return Err("invalid kind literal"); }
        if !(1_i64..=3600_i64).contains(&self.freshness_seconds) { return Err("freshness_seconds out of bounds"); }
        if !(1_i64..=86400_i64).contains(&self.lookback_seconds) { return Err("lookback_seconds out of bounds"); }
        Ok(())
    }
}

pub const FORECAST_HISTORY_CHECKPOINT_STATE: &str = "checkpoint";
impl ForecastHistoryBinding {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn canonical_states(mut values: Vec<String>) -> Result<Vec<String>, &'static str> {
        if ((((values.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((values.clone()).len() as i64)) {
            return Err("forecast history states must be unique");
        }
        Ok({ let mut _v = values.clone(); _v.sort(); _v })
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn unique_states(&self) -> Result<ForecastHistoryBinding, &'static str> {
        if (self.to_states.clone()).contains(&(String::from(FORECAST_HISTORY_CHECKPOINT_STATE))) {
            return Err("forecast history states cannot use the reserved checkpoint state");
        }
        if matches!(self.kind.as_str(), "resource_lifecycle" | "excluded_windows") {
        } else if !(self.active_states.clone()).is_empty() {
            return Err("event history cannot declare stateful exclusion mappings");
        }
        Ok(self.clone())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StateTransitionForecastHistoryCollector {
    pub initialized: bool,
}

impl StateTransitionForecastHistoryCollector {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn collect(&self, mut request: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        let mut results: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        Ok(results.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn group_forecast_history_bindings(mut bindings: Vec<ForecastHistoryBinding>) -> Result<std::collections::BTreeMap<String, std::collections::BTreeMap<String, ForecastHistoryBinding>>, &'static str> {
    if ((bindings.clone()).is_empty()) || ((((bindings.clone()).len() as i64)) > (256_i64)) {
        return Err("forecast history bindings must contain between one and 64 targets");
    }
    let groups: std::collections::BTreeMap<String, std::collections::BTreeMap<String, ForecastHistoryBinding>> = std::collections::BTreeMap::<String, std::collections::BTreeMap<String, ForecastHistoryBinding>>::new();
    Ok(groups.clone())
}

