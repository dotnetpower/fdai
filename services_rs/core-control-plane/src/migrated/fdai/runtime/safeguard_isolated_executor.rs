#[derive(Clone, Debug, Default, PartialEq)]
pub struct SafeguardBoundEventBusDirectApiExecutionClient {
    pub client: String,
    pub coordinator: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RemoteDirectApiLifecycleDispatchPort {
    pub initialized: bool,
}

impl RemoteDirectApiLifecycleDispatchPort {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn dispatch(&mut self, mut evidence_record: String, mut started_at: String, mut pre_invoke_guard: String) -> Result<(String, String, Option<String>, Option<String>), &'static str> {
        Ok((String::new(), String::new(), None, None))
    }
}

impl SafeguardBoundEventBusDirectApiExecutionClient {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn execute(&self, mut action: String, mut source_guard: Option<String>) -> Result<String, &'static str> {
        Err("safeguard dispatch result was not classified")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn unknown() -> (String, String, (), ()) {
    (String::new(), String::new(), (), ())
}

pub const PUBLIC_EXPORTS: &[&str] = &["SafeguardBoundEventBusDirectApiExecutionClient"];
