#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn audit_window(mut value: Option<String>) -> Result<Option<i64>, &'static str> {
    let Some(mut value) = value.clone() else { return Ok(None); };
    Ok(Some(((value.clone()).chars().take((-1_i64).max(0) as usize).collect::<String>()).trim().parse::<i64>().unwrap_or(0)))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn audit_sequence(mut value: Option<String>) -> Result<Option<i64>, &'static str> {
    let Some(mut value) = value.clone() else { return Ok(None); };
    Ok(Some((value.clone()).trim().parse::<i64>().unwrap_or(0)))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn audit_include_summary(mut value: Option<String>) -> Result<bool, &'static str> {
    let Some(mut value) = value.clone() else { return Ok(false); };
    if (value.clone()) != (String::from("true")) {
        return Err("audit summary MUST be true when supplied");
    }
    Ok(true)
}

