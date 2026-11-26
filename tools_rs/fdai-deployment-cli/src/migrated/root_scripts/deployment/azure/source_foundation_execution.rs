#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn prepare_source_execution(mut plan_directory: String, mut source_snapshot: String, mut source_snapshot_digest: String, mut terraform: String, mut context: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    if plan_directory.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn copy_private_tree(mut source: String, mut destination: String) -> Result<(), &'static str> {
    if source.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

