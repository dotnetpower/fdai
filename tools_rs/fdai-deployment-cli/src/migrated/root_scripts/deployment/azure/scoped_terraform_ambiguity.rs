pub const RUN_COMMAND_OPERATION: &str = "Microsoft.Compute/virtualMachines/runCommand/action";
pub const TERMINAL: &[&str] = &["Succeeded", "Failed", "Canceled"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AmbiguousOutcomeError {
    pub message: String,
}

impl AmbiguousOutcomeError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AmbiguousOutcomeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AmbiguousOutcomeError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn marker_path(mut state_root: String, mut target_key: String) -> String {
    if state_root.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn record(mut state_root: String, mut target_key: String, mut operation_id: String, mut operation: String, mut started_at: String) {
    let path: String = marker_path(state_root.clone(), target_key.clone());
    let value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("operation_id"), operation_id.clone()), (String::from("operation"), operation.clone()), (String::from("started_at"), String::new())]);
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn moment(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn invocation_state(mut run: String, mut vm_resource_id: String, mut since: String) -> String {
    let invocations: std::collections::BTreeMap<String, std::collections::BTreeSet<String>> = std::collections::BTreeMap::<String, std::collections::BTreeSet<String>>::new();
    if (invocations.clone()).is_empty() {
        return String::from("unrecorded");
    }
    String::from("running")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn require_settled(mut run: String, mut state_root: String, mut target_key: String, mut vm_resource_id: String, mut operation_id: String, mut operation: String) -> Result<bool, &'static str> {
    let path: String = marker_path(state_root.clone(), target_key.clone());
    let state: String = invocation_state(run.clone(), vm_resource_id.clone(), moment(String::new()));
    if (state.clone()) != (String::from("settled")) {
        return Err("the previous markeroperation Run Command is state in the Activity Log  w");
    }
    Ok(true)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn clear(mut state_root: String, mut target_key: String) {
    if state_root.is_empty() {
        return;
    }
}

