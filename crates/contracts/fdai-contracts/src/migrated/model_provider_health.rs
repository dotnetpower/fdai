#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ModelProviderHealth {
    #[default]
    Healthy,
    Unhealthy,
    Unknown,
}

impl ModelProviderHealth {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Healthy => "healthy",
            Self::Unhealthy => "unhealthy",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConfiguredModelBindingV1 {
    pub role: String,
    pub binding_digest: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelProviderRegistrationV1 {
    pub process_instance: String,
    pub source_artifact_digest: Option<String>,
    pub configured_bindings: Vec<ConfiguredModelBindingV1>,
    pub registration_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelProviderObservationV1 {
    pub scope_kind: String,
    pub role: String,
    pub binding_digest: Option<String>,
    pub source: String,
    pub health: ModelProviderHealth,
    pub value: Option<i64>,
    pub observed_at: Option<String>,
    pub maximum_age_seconds: i64,
    pub fresh: bool,
    pub reason: String,
    pub execution_authority: bool,
}

impl ModelProviderObservationV1 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.scope_kind.as_str(), "process_model_adapter") { return Err("invalid scope_kind literal"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.maximum_age_seconds) { return Err("maximum_age_seconds out of bounds"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelProviderScopeSnapshotV1 {
    pub schema_version: String,
    pub scope_kind: String,
    pub process_instance: String,
    pub registration_digest: Option<String>,
    pub parent_snapshot_digest: String,
    pub configured_bindings: Vec<ConfiguredModelBindingV1>,
    pub observations: Vec<ModelProviderObservationV1>,
    pub generated_at: String,
    pub coverage_complete: bool,
    pub health: ModelProviderHealth,
    pub snapshot_digest: String,
    pub execution_authority: bool,
}

impl ModelProviderScopeSnapshotV1 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.scope_kind.as_str(), "process_configured_model_roles") { return Err("invalid scope_kind literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

impl ModelProviderRegistrationV1 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn pin(&self) -> Result<String, &'static str> {
        Err("runtime_binding_required")
    }
}

impl ModelProviderObservationV1 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn aware(mut value: Option<String>) -> Result<Option<String>, &'static str> {
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn shape(&self) -> Result<String, &'static str> {
        Err("runtime_binding_required")
    }
}

impl ModelProviderScopeSnapshotV1 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn aware(mut value: String) -> Result<String, &'static str> {
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn coverage(&self) -> Result<String, &'static str> {
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_model_provider_registration(mut scope: ModelProviderScopeSnapshotV1, mut registration: ModelProviderRegistrationV1) -> Result<(), &'static str> {
    let expected: Option<String> = if (registration.source_artifact_digest.clone()).is_some() { Some(registration.registration_digest.clone()) } else { None };
    Ok(())
}

