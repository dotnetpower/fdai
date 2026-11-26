pub trait ForecastHistoryCollector {
    fn collect(&self, request: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProducingForecastHistoryCollector {
    pub initialized: bool,
}

impl ProducingForecastHistoryCollector {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn bound_kinds(&self) -> std::collections::BTreeSet<String> {
        std::collections::BTreeSet::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn collect(&self, mut request: String) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn produce(&self, mut kind: String, mut producer: String, mut request: String) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ForecastHistoryCollector", "ProducingForecastHistoryCollector"];
