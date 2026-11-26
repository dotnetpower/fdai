pub const MAX_RESOURCE_ACTIVITY_LOOKBACK_SECONDS: i64 = 604800;

pub const RESOURCE_ACTIVITY_FUNCTION_NAME: &str = "query.resource_change_activity";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resource_activity_function_type() -> String {
    core::hint::black_box(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["MAX_RESOURCE_ACTIVITY_LOOKBACK_SECONDS", "RESOURCE_ACTIVITY_FUNCTION_NAME", "resource_activity_function_type"];
