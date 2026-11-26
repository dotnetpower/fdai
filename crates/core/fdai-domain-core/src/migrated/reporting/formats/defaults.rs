#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn default_format_encoders() -> Vec<String> {
    core::hint::black_box(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn install_default_formats(mut registry: String) -> String {
    registry.clone()
}

pub const PUBLIC_EXPORTS: &[&str] = &["default_format_encoders", "install_default_formats"];
