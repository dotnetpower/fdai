#[derive(Clone, Debug, Default, PartialEq)]
pub struct AdaptiveObservationSourceMetadata {
    pub source_kind: String,
    pub receipt_digest: String,
    pub recipe_id: String,
    pub recipe_version: String,
    pub disposition: String,
    pub observed_until: Option<String>,
    pub route_count: i64,
    pub queried_route_count: i64,
    pub row_count: i64,
    pub latency_ms: i64,
    pub complete: bool,
    pub truncated: bool,
}

impl AdaptiveObservationSourceMetadata {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.source_kind.as_str(), "telemetry_recipe") { return Err("invalid source_kind literal"); }
        Ok(())
    }
}

pub trait AdaptiveExecutionMaterial {
    fn round_index(&self) -> Option<String>;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn execution_actual_cost_units(mut results: std::collections::BTreeMap<String, String>, mut reserved_cost_units: i64) -> Result<Option<i64>, &'static str> {
    let mut values: Vec<i64> = Vec::<i64>::new();
    if (values.clone()).is_empty() {
        return Ok(None);
    }
    Ok(None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn execution_source_metadata(mut results: std::collections::BTreeMap<String, String>) -> Result<Option<AdaptiveObservationSourceMetadata>, &'static str> {
    let mut candidates: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    if (candidates.clone()).is_empty() {
        return Ok(None);
    }
    if (((candidates.clone()).len() as i64)) != (1_i64) {
        return Err("adaptive query returned multiple source metadata records");
    }
    let mut observed_until: Option<String> = None;
    Ok(Some(AdaptiveObservationSourceMetadata { source_kind: String::from("telemetry_recipe"), observed_until: observed_until.clone(), ..Default::default() }))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_source_metadata_lineage(mut execution: String, mut frame_cutoff: String) -> Result<(), &'static str> {
    if execution.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn covers_evidence_cutoff(mut route_count: i64, mut queried_route_count: i64, mut observed_until: Option<String>, mut cutoff: String, mut disposition: String) -> bool {
    if ((route_count) <= (0_i64)) || (((queried_route_count) != (route_count)) || (observed_until.is_none())) {
        return false;
    }
    if ((observed_until.clone()).unwrap_or_default()) > (cutoff.clone()) {
        return false;
    }
    ((disposition.clone()) == (String::from("complete"))) || (((disposition.clone()) == (String::from("complete_no_data"))) && ((observed_until.clone()) == Some(cutoff.clone())))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn source_metadata_material(mut metadata: AdaptiveObservationSourceMetadata) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("source_kind"), metadata.source_kind.clone()), (String::from("receipt_digest"), metadata.receipt_digest.clone()), (String::from("recipe_id"), metadata.recipe_id.clone()), (String::from("recipe_version"), metadata.recipe_version.clone()), (String::from("disposition"), metadata.disposition.clone()), (String::from("observed_until"), String::new()), (String::from("route_count"), String::new()), (String::from("queried_route_count"), String::new()), (String::from("row_count"), String::new()), (String::from("latency_ms"), String::new()), (String::from("complete"), String::new()), (String::from("truncated"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn execution_material(mut execution: String) -> std::collections::BTreeMap<String, String> {
    let mut material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("round_index"), String::new()), (String::from("frame_digest"), String::new()), (String::from("selection_digest"), String::new()), (String::from("candidate_digest"), String::new()), (String::from("binding_digest"), String::new()), (String::from("verification_receipt_digest"), String::new()), (String::from("plan_digest"), String::new()), (String::from("result_digest"), String::new()), (String::from("query_status"), String::new()), (String::from("evidence_refs"), String::new()), (String::from("reserved_cost_units"), String::new()), (String::from("actual_cost_units"), String::new()), (String::from("execution_authority"), String::new()), (String::from("mutation_authority"), String::new())]);
    material.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn text(mut name: String, mut value: String) -> Result<(), &'static str> {
    if (((value.clone()).trim().to_string()).is_empty()) || ((((value.clone()).len() as i64)) > (512_i64)) {
        return Err("name MUST be non-empty and bounded");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn digest(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn aware(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["AdaptiveObservationSourceMetadata", "execution_actual_cost_units", "_execution_material", "execution_source_metadata", "_source_metadata_material", "validate_source_metadata_lineage"];
