#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn install_shutdown_signals() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn executor_process_lock() -> Result<String, &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn run_main(mut run: String) -> i64 {
    0_i64
}

pub const PUBLIC_EXPORTS: &[&str] = &["executor_process_lock", "install_shutdown_signals", "run_main"];
