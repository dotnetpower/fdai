#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn register(mut provision_commands: String, mut command: String, mut handlers: std::collections::BTreeMap<String, String>) {
    if provision_commands.is_empty() {
        return;
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["register"];
