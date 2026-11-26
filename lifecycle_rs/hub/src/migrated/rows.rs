#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn get_installation(mut session: String, mut installation_id: String) -> Result<String, &'static str> {
    if session.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn lock_installation(mut session: String, mut installation_id: String) -> Result<String, &'static str> {
    if session.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn lock_enrolled(mut session: String, mut installation_id: String) -> Result<String, &'static str> {
    let row: String = lock_installation(session.clone(), installation_id.clone()).unwrap_or_else(|_| String::new());
    Ok(row.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn lock_pending(mut session: String, mut installation_id: String) -> Result<String, &'static str> {
    let row: String = lock_installation(session.clone(), installation_id.clone()).unwrap_or_else(|_| String::new());
    Ok(row.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn entity_row(mut session: String, mut installation_id: String, mut entity_id: String) -> Result<String, &'static str> {
    if session.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn store_suppressions(mut row: String, mut installation: String, mut now: String) {
    if row.is_empty() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn supersede(mut session: String, mut plan: Option<String>, mut now: String) {
    if session.is_empty() {
        return;
    }
}

