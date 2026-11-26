#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResourceAvailabilityBinding {
    pub resource_ref: String,
    pub resource_type: String,
    pub provider_ref: String,
    pub scope_ref: String,
}

impl ResourceAvailabilityBinding {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.resource_ref.trim().is_empty() { return Err("resource_ref must be non-empty"); }
        if self.resource_type.trim().is_empty() { return Err("resource_type must be non-empty"); }
        if self.provider_ref.trim().is_empty() { return Err("provider_ref must be non-empty"); }
        if self.scope_ref.trim().is_empty() { return Err("scope_ref must be non-empty"); }
        Ok(())
    }
}

pub trait AvailabilityInventoryReader {
    fn read_active_resources(&self, resource_ids: Vec<String>) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InventoryResourceAvailabilitySource {
    pub initialized: bool,
}

impl InventoryResourceAvailabilitySource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observe(&self, mut resource_ref: String, mut since: String, mut until: String) -> Result<String, &'static str> {
        let mut reason: Option<String> = None;
        let mut state_metadata: Option<String> = None;
        let revision: Option<String> = None;
        let mut record: Option<String> = None;
        let valid: bool = (record.is_some()) && (reason.is_none());
        Ok(String::new())
    }
}

