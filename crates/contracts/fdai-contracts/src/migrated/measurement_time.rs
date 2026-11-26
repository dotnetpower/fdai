#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn measurement_timestamp_input(mut value: String) -> Result<String, &'static str> {
    if !(true) {
        return Err("measurement timestamps require aware datetime or ISO 8601 text");
    }
    Ok(value.clone())
}

