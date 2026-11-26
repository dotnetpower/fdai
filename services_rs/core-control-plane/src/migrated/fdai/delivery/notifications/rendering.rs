pub const TRUNCATION_MARKER: &str = " [truncated]";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn truncate_with_marker(mut value: String, mut limit: i64) -> Result<(String, bool), &'static str> {
    if (limit) <= (((String::from(TRUNCATION_MARKER)).len() as i64)) {
        return Err("rendering limit MUST exceed the truncation marker length");
    }
    if (((value.clone()).len() as i64)) <= (limit) {
        return Ok((value.clone(), false));
    }
    Ok((String::new(), false))
}

pub const PUBLIC_EXPORTS: &[&str] = &["truncate_with_marker"];
