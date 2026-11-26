#[derive(Clone, Debug, Default, PartialEq)]
pub struct CatalogEscalationTiming {
    pub catalog: String,
    pub environment: String,
    pub audiences: Option<String>,
    pub urgency_policy_id: String,
}

impl CatalogEscalationTiming {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    #[allow(clippy::type_complexity)]
    pub fn resolve(&self, mut context: Option<std::collections::BTreeMap<String, String>>, mut subjects: Vec<String>, mut at: Option<String>) -> std::collections::BTreeMap<String, String> {
        let Some(mut context) = context.clone() else { return std::collections::BTreeMap::from([(String::from("catalog_status"), String::from("context_unavailable"))]); };
        let finding: Option<String> = (context.clone()).get("finding_class").cloned();
        let impact: Option<String> = (context.clone()).get("impact").cloned();
        if (!(true)) || ((!(true)) || (!(matches!(((impact.clone()).unwrap_or_default()).as_str(), "resource" | "resource_group" | "subscription")))) {
            return std::collections::BTreeMap::from([(String::from("catalog_status"), String::from("context_unavailable"))]);
        }
        if self.audiences.is_none() {
            return std::collections::BTreeMap::from([(String::from("catalog_status"), String::from("audience_unavailable")), (String::from("catalog_id"), String::new())]);
        }
        let verified: Option<String> = (context.clone()).get("verified_forecast_urgency").cloned();
        std::collections::BTreeMap::from([(String::from("catalog_status"), String::from("resolved")), (String::from("catalog_id"), String::new()), (String::from("catalog_overall_seconds"), String::new()), (String::from("catalog_ttl_seconds"), String::new()), (String::from("catalog_compressed"), String::new()), (String::from("forecast_timing_status"), String::from("verified\" if lead is not None else \"unavailable")), (String::from("forecast_timing_digest"), String::new())])
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["CatalogEscalationTiming"];
