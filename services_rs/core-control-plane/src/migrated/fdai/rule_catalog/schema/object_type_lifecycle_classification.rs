use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ObjectTypeLifecycleClassification {
    #[default]
    CatalogAsCode,
    EventBusRegistry,
    ProjectionOwned,
    OwnerRequired,
}

impl ObjectTypeLifecycleClassification {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::CatalogAsCode => "catalog_as_code",
            Self::EventBusRegistry => "event_bus_registry",
            Self::ProjectionOwned => "projection_owned",
            Self::OwnerRequired => "owner_required",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObjectTypeLifecycleClassificationGroup {
    pub rationale: String,
    pub source_refs: Vec<String>,
    pub object_types: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObjectTypeLifecycleClassificationRegistry {
    pub schema_version: String,
    pub categories: BTreeMap<ObjectTypeLifecycleClassification, ObjectTypeLifecycleClassificationGroup>,
}

impl ObjectTypeLifecycleClassificationGroup {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_values(&self) -> Result<ObjectTypeLifecycleClassificationGroup, &'static str> {
        Err("runtime_binding_required")
    }
}

impl ObjectTypeLifecycleClassificationRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn complete_categories(&self) -> Result<ObjectTypeLifecycleClassificationRegistry, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn classified_names(&self) -> std::collections::BTreeSet<String> {
        std::collections::BTreeSet::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_object_type_lifecycle_classification_registry(mut path: String, mut object_types: Vec<String>) -> Result<ObjectTypeLifecycleClassificationRegistry, &'static str> {
    if path.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ObjectTypeLifecycleClassification", "ObjectTypeLifecycleClassificationGroup", "ObjectTypeLifecycleClassificationRegistry", "load_object_type_lifecycle_classification_registry"];
