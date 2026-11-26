pub const IDENTITY_FIELDS: &[&str] = &["resource_ref", "gpu_id", "model", "observed_at"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn normalize_sample(mut source: String, mut identity: std::collections::BTreeMap<String, String>, mut metrics: std::collections::BTreeMap<String, String>, mut metric_names: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    if source.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

