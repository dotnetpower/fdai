#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn main(mut retain_only: bool) -> Result<(), &'static str> {
    if retain_only {
        return Ok(());
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn main_fn() -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

