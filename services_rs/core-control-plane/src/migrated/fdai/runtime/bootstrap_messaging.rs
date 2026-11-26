#[derive(Clone, Debug, Default, PartialEq)]
pub struct MessagingRuntime {
    pub bus: String,
    pub auxiliary_bus: Option<String>,
    pub operational_bus: String,
    pub stage_publisher: String,
    pub diagnostic_bus: Option<String>,
}

pub trait EventBusFactory {
    fn call(&self, identity: Option<String>, config: String) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn build_messaging_runtime(mut plan: String, mut kafka: String, mut identity: Option<String>, mut bus_factory: String) -> Result<MessagingRuntime, &'static str> {
    let mut auxiliary_bus: Option<String> = None;
    let mut diagnostic_bus: Option<String> = None;
    Ok(MessagingRuntime { auxiliary_bus: auxiliary_bus.clone(), diagnostic_bus: diagnostic_bus.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn operating_model_event_bus(mut messaging: MessagingRuntime) -> String {
    messaging.bus.clone()
}

pub const PUBLIC_EXPORTS: &[&str] = &["EventBusFactory", "MessagingRuntime", "build_messaging_runtime", "operating_model_event_bus"];
