use std::collections::BTreeMap;
pub const MAX_CAPACITY: i64 = 10000000;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ModelSelectionMode {
    #[default]
    Auto,
    Pinned,
    HilOnly,
}

impl ModelSelectionMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Auto => "auto",
            Self::Pinned => "pinned",
            Self::HilOnly => "hil-only",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ModelSku {
    #[default]
    Standard,
    GlobalStandard,
    ProvisionedManaged,
    GlobalProvisionedManaged,
    DataZoneProvisionedManaged,
}

impl ModelSku {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Standard => "Standard",
            Self::GlobalStandard => "GlobalStandard",
            Self::ProvisionedManaged => "ProvisionedManaged",
            Self::GlobalProvisionedManaged => "GlobalProvisionedManaged",
            Self::DataZoneProvisionedManaged => "DataZoneProvisionedManaged",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelBindingCapacity {
    pub unit: String,
    pub value: i64,
}

impl ModelBindingCapacity {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.unit.as_str(), "tpm" | "ptu") { return Err("invalid unit literal"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.value) { return Err("value out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CapabilityBindingPolicy {
    pub selection_mode: ModelSelectionMode,
    pub publisher: Option<String>,
    pub family: Option<String>,
    pub version_policy: Option<String>,
    pub sku: Option<ModelSku>,
    #[allow(clippy::type_complexity)]
    pub capacity: Option<Box<ModelBindingCapacity>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelBindingPolicy {
    pub schema_version: String,
    pub environment: String,
    pub revision: i64,
    pub expected_active_digest: Option<String>,
    pub capabilities: BTreeMap<String, CapabilityBindingPolicy>,
}

impl ModelBindingPolicy {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.revision) { return Err("revision out of bounds"); }
        Ok(())
    }
}

pub const CAPABILITY: &str = "^(t1|t2)\\.[a-z][a-z0-9._-]{1,63}$";
pub const PUBLISHER_PATTERN: &str = "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$";
pub const FAMILY_PATTERN: &str = "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$";
impl CapabilityBindingPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_mode_shape(&self) -> Result<CapabilityBindingPolicy, &'static str> {
        let expected_unit: String = String::from("ptu\" if sku.is_provisioned else \"tpm");
        Ok(self.clone())
    }
}

impl ModelBindingPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_capability_names(&self) -> Result<ModelBindingPolicy, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        core::hint::black_box(String::new())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["CapabilityBindingPolicy", "ModelBindingCapacity", "ModelBindingPolicy", "ModelSelectionMode", "ModelSku"];
