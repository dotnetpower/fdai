pub const RESOURCE_GROUP: &str = "[A-Za-z0-9_.()-]{1,90}";
pub const RESOURCE_NAME: &str = "[A-Za-z0-9_.()-]{1,128}";
pub const RESOURCE_TYPE: &str = "[A-Za-z0-9_.-]{1,128}(?:/[A-Za-z0-9_.-]{1,128})?";
pub const SUBSCRIPTION: &str = "[A-Za-z0-9-]{1,64}";
pub const TIMESTAMP: &str = "[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.-]+Z";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn default_command_catalog() -> String {
    core::hint::black_box(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["default_command_catalog"];
