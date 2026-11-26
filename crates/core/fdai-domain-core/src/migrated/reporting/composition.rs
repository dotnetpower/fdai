#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn provenance(mut name: String, mut wired: bool) -> String {
    if name.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn default_reporting_engine(mut reports_root: Option<String>, mut audit_reader: Option<String>, mut report_feed: Option<String>, mut metric_provider: Option<String>, mut log_query_provider: Option<String>, mut ontology_store: Option<String>, mut process_store: Option<String>, mut ontology_object_types: Vec<String>, mut ontology_projection_request: Option<String>) -> Result<(String, String), &'static str> {
    if (ontology_store.is_some()) && (process_store.is_some()) {
        if (ontology_object_types.clone()).is_empty() {
            return Err("ontology_object_types MUST be provided when the ontology datasource is w");
        }
    }
    Ok((String::new(), String::new()))
}

pub const PUBLIC_EXPORTS: &[&str] = &["default_reporting_engine"];
