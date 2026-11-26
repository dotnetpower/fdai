use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperatorRuntime {
    pub environment: String,
    pub authenticator: String,
    pub read_model: String,
    pub data_sources: Vec<String>,
    pub route_families: String,
    pub readiness_probe: String,
    pub live_stream_hub: String,
    pub agent_stream_hub: String,
    #[allow(clippy::type_complexity)]
    pub local_cli_profile: Option<BTreeMap<String, String>>,
    pub local_cli_session_token: Option<String>,
    pub lifecycle: Option<String>,
}

impl OperatorRuntime {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn create_app(&self) -> String {
        core::hint::black_box(String::new())
    }
}

