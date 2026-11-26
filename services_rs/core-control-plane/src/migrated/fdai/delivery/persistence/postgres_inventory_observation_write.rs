pub const WRITE_BATCH_SIZE: i64 = 1000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryObservationAppendResult {
    pub high_watermark: i64,
    pub inserted: i64,
}

pub const INVENTORY_OBSERVATION_WATERMARK_KEY: &str = "inventory-observation:watermarks";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn append_records(mut connection: String, mut observations: Vec<String>) -> Result<InventoryObservationAppendResult, &'static str> {
    if (observations.clone()).is_empty() {
        return Ok(InventoryObservationAppendResult::default());
    }
    let mut inserted: i64 = 0_i64;
    let mut retained_watermarks: Vec<i64> = Vec::<i64>::new();
    Ok(InventoryObservationAppendResult::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn update_watermark_state(mut connection: String, mut journal_watermark: Option<i64>, mut overlay_watermark: Option<i64>, mut ontology_watermark: Option<i64>, mut ontology_generation: Option<String>) -> Result<(), &'static str> {
    let value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("journal_high_watermark"), String::new()), (String::from("overlay_projection_watermark"), String::new()), (String::from("ontology_projection_watermark"), String::new()), (String::from("ontology_generation"), String::new()), (String::from("pending_tombstones"), String::new()), (String::from("mode"), String::from("shadow"))]);
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["INVENTORY_OBSERVATION_WATERMARK_KEY", "InventoryObservationAppendResult", "append_records", "update_watermark_state"];
