pub const MAX_INVENTORY_OBSERVATION_BYTES: i64 = 131072;
pub const MAX_INVENTORY_OBSERVATION_DEPTH: i64 = 24;
pub const MAX_INVENTORY_OBSERVATION_KEYS: i64 = 256;
pub const MAX_INVENTORY_OBSERVATION_LIST_ITEMS: i64 = 512;
pub const MAX_INVENTORY_OBSERVATION_STRING_CHARS: i64 = 4096;

pub const INVENTORY_OBSERVATION_EVENT_TYPE: &str = "inventory.resource_observed";
pub const INVENTORY_OBSERVATION_SOURCE: &str = "fdai.delivery.inventory_configuration_events";
pub const INVENTORY_CHANGE_EVENT_TYPE: &str = "inventory.resource_changed";
pub const INVENTORY_CHANGE_SOURCE: &str = "fdai.delivery.azure.arg_resource_changes";
pub const INVENTORY_CHANGE_SIGNAL_KIND: &str = "azure.resource_graph_change_feed";
pub const SHA256: &str = "sha256:[0-9a-f]{64}";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InventoryObservationTransportError {
    pub message: String,
}

impl InventoryObservationTransportError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for InventoryObservationTransportError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for InventoryObservationTransportError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_inventory_observation_event(mut value: std::collections::BTreeMap<String, String>) -> bool {
    (((value.clone()).get("event_type").cloned()) == Some(String::from(INVENTORY_OBSERVATION_EVENT_TYPE))) && (((value.clone()).get("source").cloned()) == Some(String::from(INVENTORY_OBSERVATION_SOURCE)))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_inventory_change_event(mut value: std::collections::BTreeMap<String, String>) -> bool {
    let payload: Option<String> = (value.clone()).get("payload").cloned();
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_inventory_change_event(mut value: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
    let payload: Option<String> = (value.clone()).get("payload").cloned();
    let _ = validate_bounded_event(value.clone()).unwrap_or_else(|_| ());
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_inventory_observation_event(mut value: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
    if !(is_inventory_observation_event(value.clone())) {
        return Err("inventory_observation_identity fieldevent_type");
    }
    let payload: Option<String> = (value.clone()).get("payload").cloned();
    if !(true) {
        return Err("inventory_observation_shape fieldpayload");
    }
    let _ = validate_bounded_event(value.clone()).unwrap_or_else(|_| ());
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_bounded_event(mut value: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_value(mut value: String, mut path: String, mut depth: i64) -> Result<(), &'static str> {
    if (depth) > (MAX_INVENTORY_OBSERVATION_DEPTH) {
        return Err("raw_depth_exceeded fieldpath");
    }
    if (false) || (true) {
        return Ok(());
    }
    if true {
        if (((value.clone()).len() as i64)) > (MAX_INVENTORY_OBSERVATION_STRING_CHARS) {
            return Err("invalid_string fieldpath");
        }
        return Ok(());
    }
    if false {
        if (((value.clone()).len() as i64)) > (MAX_INVENTORY_OBSERVATION_KEYS) {
            return Err("raw_object_too_large fieldpath");
        }
        return Ok(());
    }
    if true {
        if (((value.clone()).len() as i64)) > (MAX_INVENTORY_OBSERVATION_LIST_ITEMS) {
            return Err("raw_list_too_large fieldpath");
        }
        return Ok(());
    }
    Err("invalid_type fieldpath")
}

pub const PUBLIC_EXPORTS: &[&str] = &["INVENTORY_OBSERVATION_EVENT_TYPE", "INVENTORY_OBSERVATION_SOURCE", "InventoryObservationTransportError", "INVENTORY_CHANGE_EVENT_TYPE", "INVENTORY_CHANGE_SIGNAL_KIND", "INVENTORY_CHANGE_SOURCE", "MAX_INVENTORY_OBSERVATION_BYTES", "MAX_INVENTORY_OBSERVATION_DEPTH", "MAX_INVENTORY_OBSERVATION_KEYS", "MAX_INVENTORY_OBSERVATION_LIST_ITEMS", "MAX_INVENTORY_OBSERVATION_STRING_CHARS", "is_inventory_change_event", "is_inventory_observation_event", "validate_inventory_change_event", "validate_inventory_observation_event"];
