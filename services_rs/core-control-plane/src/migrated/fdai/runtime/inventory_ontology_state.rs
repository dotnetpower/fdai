#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum InventoryOntologyProjectionStatus {
    #[default]
    Available,
    Unavailable,
}

impl InventoryOntologyProjectionStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Available => "available",
            Self::Unavailable => "unavailable",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryOntologyProjectionResult {
    pub generation: String,
    pub ontology_release_digest: String,
    pub status: InventoryOntologyProjectionStatus,
    pub object_count: i64,
    pub link_count: i64,
    pub complete: bool,
    pub relationship_complete: bool,
    pub dropped_reasons: Vec<String>,
    pub journal_high_watermark: Option<i64>,
    pub projection_high_watermark: Option<i64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryProjectionCheckpoints {
    pub journal_high_watermark: Option<i64>,
    pub projection_high_watermark: Option<i64>,
    pub active_scope_projection_watermark: Option<i64>,
    pub active_scope_refs: Vec<String>,
}

impl InventoryProjectionCheckpoints {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    #[allow(clippy::type_complexity)]
    pub fn active_scope_state(&self, mut generation: String) -> Option<std::collections::BTreeMap<String, String>> {
        if self.active_scope_projection_watermark.is_none() {
            return None;
        }
        Some(std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("generation"), generation.clone()), (String::from("scope_refs"), String::new()), (String::from("journal_high_watermark"), String::new()), (String::from("projection_high_watermark"), String::new())]))
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InventoryOntologyProjectionResult", "InventoryOntologyProjectionStatus", "InventoryProjectionCheckpoints"];
