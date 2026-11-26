#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn current_correlation_id() -> Option<String> {
    core::hint::black_box(None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn with_correlation(mut correlation_id: String) -> Result<Vec<()>, &'static str> {
    if (correlation_id.clone()).is_empty() {
        return Err("correlation_id MUST be a non-empty string");
    }
    Ok(Vec::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["current_correlation_id", "with_correlation"];
