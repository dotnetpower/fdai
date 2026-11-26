pub const FORECAST_HISTORY_COLLECTION_KEY: &str = "forecast.history_collection.enabled";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PreferenceGatedForecastHistoryCollector {
    pub initialized: bool,
}

impl PreferenceGatedForecastHistoryCollector {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn preference(&self) -> Result<(bool, i64), &'static str> {
        Ok((false, 0_i64))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn collect(&self, mut request: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(std::collections::BTreeMap::new())
    }
}

