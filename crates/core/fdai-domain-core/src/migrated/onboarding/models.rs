use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OnboardingResourceKind {
    #[default]
    ExecutorIdentity,
    Runtime,
    ContainerRegistry,
    StateStore,
    EventBus,
    SecretStore,
    ObservabilityLogs,
    ObservabilityApm,
}

impl OnboardingResourceKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ExecutorIdentity => "executor_identity",
            Self::Runtime => "runtime",
            Self::ContainerRegistry => "container_registry",
            Self::StateStore => "state_store",
            Self::EventBus => "event_bus",
            Self::SecretStore => "secret_store",
            Self::ObservabilityLogs => "observability_logs",
            Self::ObservabilityApm => "observability_apm",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExpectedResource {
    pub kind: OnboardingResourceKind,
    pub description: String,
    pub required: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExpectedRoleAssignment {
    pub principal_ref: String,
    pub role: String,
    pub scope_kind: OnboardingResourceKind,
    pub description: String,
    pub required: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObservedResource {
    pub kind: OnboardingResourceKind,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObservedRoleAssignment {
    pub principal_ref: String,
    pub role: String,
    pub scope_kind: OnboardingResourceKind,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OnboardingSpec {
    pub resources: Vec<ExpectedResource>,
    pub role_assignments: Vec<ExpectedRoleAssignment>,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OnboardingReport {
    pub ready: bool,
    pub missing_resources: Vec<OnboardingResourceKind>,
    pub missing_role_assignments: Vec<String>,
    pub present_resource_count: i64,
    pub present_role_count: i64,
    pub error: Option<String>,
}

impl ExpectedRoleAssignment {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn key(&self) -> (String, String, String) {
        (String::new(), String::new(), String::new())
    }
}

impl ObservedRoleAssignment {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn key(&self) -> (String, String, String) {
        (String::new(), String::new(), String::new())
    }
}

impl OnboardingReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn blocked(&self) -> bool {
        !(self.ready)
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ExpectedResource", "ExpectedRoleAssignment", "ObservedResource", "ObservedRoleAssignment", "OnboardingReport", "OnboardingResourceKind", "OnboardingSpec"];
