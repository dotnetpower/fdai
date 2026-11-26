pub trait AsyncCloseable {
    fn close(&self) -> String;
}

pub trait AsyncStoppable {
    fn stop(&self) -> String;
}

pub trait AsyncAcloseable {
    fn aclose(&self) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::too_many_arguments)]
pub async fn close_runtime_resources(mut health_server: Option<String>, mut pantheon_runtime: Option<String>, mut runtime_state_publisher: Option<String>, mut diagnostic_bus: Option<String>, mut auxiliary_bus: Option<String>, mut bus: Option<String>, mut http_client: Option<String>, mut state_store: Option<String>) {
    if health_server.is_none() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn close_bus(mut bus: Option<String>, mut warning: String) {
    let Some(mut bus) = bus.clone() else { return; };
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn aclose_optional(mut resource: Option<String>, mut warning: String) {
    let Some(mut resource) = resource.clone() else { return; };
}

pub const PUBLIC_EXPORTS: &[&str] = &["close_runtime_resources"];
