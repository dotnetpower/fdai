#[derive(Clone, Debug, Default, PartialEq)]
pub struct UnavailableSelfHealthExporter {
    pub signal: String,
    pub metric: String,
    pub exporter_id: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct UnavailableOperationalStateExporter {
    pub field_name: String,
    pub exporter_id: String,
    pub maximum_age_seconds: i64,
}

impl UnavailableSelfHealthExporter {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observe(&self, mut now: String) -> Result<String, &'static str> {
        Err("self.signal.value")
    }
}

impl UnavailableOperationalStateExporter {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observe(&self, mut now: String) -> Result<String, &'static str> {
        Err("self.field_name.value")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn unavailable_self_health_registry(mut catalog: String) -> String {
    if catalog.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["UnavailableOperationalStateExporter", "UnavailableSelfHealthExporter", "unavailable_self_health_registry"];
