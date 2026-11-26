#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PanelStatus {
    #[default]
    Available,
    Unavailable,
}

impl PanelStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Available => "available",
            Self::Unavailable => "unavailable",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MetricObservation {
    pub metric_key: String,
    pub value: f64,
    pub observed_at: String,
    pub producer: String,
    pub synthetic: bool,
}

impl MetricObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.metric_key.trim().is_empty() { return Err("metric_key must be non-empty"); }
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        if self.producer.trim().is_empty() { return Err("producer must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PanelReading {
    pub panel_id: String,
    pub status: PanelStatus,
    pub value: Option<f64>,
    pub reason: Option<String>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn resolve_dashboard_readings(mut descriptor: std::collections::BTreeMap<String, String>, mut observations: Vec<MetricObservation>, mut as_of: String, mut live: bool) -> Result<Vec<PanelReading>, &'static str> {
    let mut by_key: std::collections::BTreeMap<String, Option<MetricObservation>> = std::collections::BTreeMap::<String, Option<MetricObservation>>::new();
    for observation in observations.clone() {
        if (by_key.clone()).contains_key((observation.metric_key.clone()).as_str()) {
            by_key.insert(observation.metric_key.clone(), None);
        } else {
            by_key.insert(observation.metric_key.clone(), Some(observation.clone()));
        }
    }
    let mut readings: Vec<PanelReading> = Vec::<PanelReading>::new();
    Ok(readings.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["MetricObservation", "PanelReading", "PanelStatus", "resolve_dashboard_readings"];
