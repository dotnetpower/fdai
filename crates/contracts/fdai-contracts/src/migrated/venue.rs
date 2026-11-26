#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ExecutionVenue {
    #[default]
    Local,
    Deployed,
}

impl ExecutionVenue {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Local => "local",
            Self::Deployed => "deployed",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum VenueCapability {
    #[default]
    BusSecurityProtocol,
    BusIdentityBinding,
    WorkloadIdentitySource,
    DocumentProviderBinding,
}

impl VenueCapability {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::BusSecurityProtocol => "bus_security_protocol",
            Self::BusIdentityBinding => "bus_identity_binding",
            Self::WorkloadIdentitySource => "workload_identity_source",
            Self::DocumentProviderBinding => "document_provider_binding",
        }
    }
}

pub const EXECUTION_VENUE_ENV: &str = "FDAI_EXECUTION_VENUE";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ExecutionVenueError {
    pub message: String,
}

impl ExecutionVenueError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ExecutionVenueError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ExecutionVenueError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn resolve_execution_venue(mut env: Option<std::collections::BTreeMap<String, String>>) -> Result<ExecutionVenue, &'static str> {
    if env.is_none() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn select_capability(mut capability: VenueCapability, mut venue: ExecutionVenue) -> Result<String, &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bus_security_protocol(mut venue: ExecutionVenue) -> Result<String, &'static str> {
    let value: String = select_capability(Default::default(), venue.clone()).unwrap_or_else(|_| String::new());
    if (value.clone()) == (String::from("PLAINTEXT")) {
        return Ok(String::from("PLAINTEXT"));
    }
    if (value.clone()) == (String::from("SASL_SSL")) {
        return Ok(String::from("SASL_SSL"));
    }
    Err("valuer is not a supported bus security protocol")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn uses_workload_identity(mut venue: ExecutionVenue) -> bool {
    (select_capability(Default::default(), venue.clone()).unwrap_or_else(|_| String::new())) != (String::from("none"))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn uses_developer_identity(mut venue: ExecutionVenue) -> bool {
    (select_capability(Default::default(), venue.clone()).unwrap_or_else(|_| String::new())) == (String::from("azure_cli"))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn uses_managed_identity(mut venue: ExecutionVenue) -> bool {
    (select_capability(Default::default(), venue.clone()).unwrap_or_else(|_| String::new())) == (String::from("managed_identity"))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn uses_local_document_providers(mut venue: ExecutionVenue) -> bool {
    (select_capability(Default::default(), venue.clone()).unwrap_or_else(|_| String::new())) == (String::from("local_substitutes"))
}

pub const PUBLIC_EXPORTS: &[&str] = &["EXECUTION_VENUE_ENV", "VENUE_CAPABILITIES", "BusSecurityProtocol", "ExecutionVenue", "ExecutionVenueError", "VenueCapability", "bus_security_protocol", "resolve_execution_venue", "select_capability", "uses_developer_identity", "uses_local_document_providers", "uses_managed_identity", "uses_workload_identity"];
