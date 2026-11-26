#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_reservation_state_shape(mut record: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["validate_reservation_state_shape"];
