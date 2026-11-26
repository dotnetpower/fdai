#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_gpu_sku_mismatch_probe(mut entry: String, mut ctx: std::collections::BTreeMap<String, String>) -> String {
    if entry.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_chaos_mesh_probe(mut entry: String, mut ctx: std::collections::BTreeMap<String, String>) -> String {
    if entry.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_litmus_probe(mut entry: String, mut ctx: std::collections::BTreeMap<String, String>) -> String {
    if entry.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_pod_restart_probe(mut entry: String, mut ctx: std::collections::BTreeMap<String, String>) -> String {
    if entry.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_backend_health_probe(mut entry: String, mut ctx: std::collections::BTreeMap<String, String>) -> String {
    if entry.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_rollout_stall_probe(mut entry: String, mut ctx: std::collections::BTreeMap<String, String>) -> String {
    if entry.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_host_cpu_probe(mut entry: String, mut ctx: std::collections::BTreeMap<String, String>) -> String {
    if entry.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_host_memory_probe(mut entry: String, mut ctx: std::collections::BTreeMap<String, String>) -> String {
    if entry.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_db_cpu_probe(mut entry: String, mut ctx: std::collections::BTreeMap<String, String>) -> String {
    if entry.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_rate_limit_probe(mut entry: String, mut ctx: std::collections::BTreeMap<String, String>) -> String {
    if entry.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_cm_status_probe(mut entry: String, mut ctx: std::collections::BTreeMap<String, String>) -> String {
    build_chaos_mesh_probe(entry.clone(), ctx.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn vm_run_command_probe(mut ctx: std::collections::BTreeMap<String, String>, mut script: String, mut expected: String) -> String {
    if ctx.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn build_azure_state_probe(mut entry: String, mut ctx: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    Err("entry.id: no Azure state probe for refr")
}

