use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ThorExecutionBindings {
    pub action_rollback_executors: BTreeMap<String, String>,
    #[allow(clippy::type_complexity)]
    pub rollback_executors: Option<BTreeMap<String, String>>,
    pub preflight_simulator: Option<String>,
    pub acceptance_scale_out_recovery_bound: bool,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn build_safety(mut config: String, mut enforce: bool) -> (Option<String>, Option<String>) {
    (None, None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_thor_execution_bindings(mut thor_mutation_bound: bool, mut t2_route_registry: String, mut acceptance_bindings: Option<String>) -> ThorExecutionBindings {
    let mut action_rollback_executors: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    let rollback_executors: Option<std::collections::BTreeMap<String, String>> = if (thor_mutation_bound) && (!((acceptance_bindings.clone()).is_some())) { Some(std::collections::BTreeMap::from([(String::from("state_forward_only"), String::new())])) } else { None };
    let mut thor_preflight_simulators: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    ThorExecutionBindings::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_typed_read_execution_bindings(mut thor_mutation_bound: bool, mut t2_route_registry: String, mut acceptance_bindings: Option<String>, mut store: String, mut admission: Option<String>, mut can_approve: Option<String>) -> (String, ThorExecutionBindings, String) {
    let bindings: ThorExecutionBindings = build_thor_execution_bindings(thor_mutation_bound, t2_route_registry.clone(), acceptance_bindings.clone());
    (String::new(), Default::default(), String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn typed_read_anomaly_sources(mut acceptance: Option<String>, mut lifecycle: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ThorExecutionBindings", "build_thor_execution_bindings", "build_typed_read_execution_bindings", "typed_read_anomaly_sources"];
