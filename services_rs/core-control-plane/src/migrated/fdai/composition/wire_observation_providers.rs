#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn attach_observation_providers(mut container: String, mut workspace_id: Option<String>, mut identity: String, mut http_client: String) -> String {
    let mut workspace_id: String = match workspace_id.clone() { Some(_v) if !_v.is_empty() => _v, _ => return container.clone() };
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn attach_telemetry_workspace_resolver(mut container: String, mut resolver: String) -> String {
    if container.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["attach_observation_providers", "attach_telemetry_workspace_resolver"];
