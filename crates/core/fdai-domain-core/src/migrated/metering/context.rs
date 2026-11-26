#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn current_invocation_scope() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn with_invocation_scope(mut scope: String) -> Vec<()> {
    core::hint::black_box(Vec::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["current_invocation_scope", "with_invocation_scope"];
