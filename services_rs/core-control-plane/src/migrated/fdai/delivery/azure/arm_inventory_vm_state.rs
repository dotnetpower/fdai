#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ArmInventoryError {
    pub message: String,
}

impl ArmInventoryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ArmInventoryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ArmInventoryError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn project_vmss_instance_state(mut row: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let properties: Option<String> = (row.clone()).get("properties").cloned();
    if !(true) {
        return Ok(row.clone());
    }
    let sanitized_view: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("powerState"), String::new())]);
    Ok(std::collections::BTreeMap::from([(String::from("properties"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn with_vm_run_command_state(mut resource: String, mut row: std::collections::BTreeMap<String, String>) -> String {
    let properties: Option<String> = (row.clone()).get("properties").cloned();
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_child_identity(mut resource_id: String, mut parent_id: String, mut collection: String) -> Result<(), &'static str> {
    let normalized: String = (resource_id.trim().to_string()).to_lowercase();
    Ok(())
}

