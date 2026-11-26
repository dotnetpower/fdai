#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DocumentOcrProvider {
    #[default]
    LocalPython,
    AzureDocumentIntelligence,
}

impl DocumentOcrProvider {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::LocalPython => "local_python",
            Self::AzureDocumentIntelligence => "azure_document_intelligence",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DocumentOcrResourceState {
    #[default]
    Absent,
    PlanRequired,
    PlanRequested,
    Provisioning,
    Verifying,
    Ready,
    Draining,
    Failed,
}

impl DocumentOcrResourceState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Absent => "absent",
            Self::PlanRequired => "plan-required",
            Self::PlanRequested => "plan-requested",
            Self::Provisioning => "provisioning",
            Self::Verifying => "verifying",
            Self::Ready => "ready",
            Self::Draining => "draining",
            Self::Failed => "failed",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DocumentOcrPolicy {
    pub schema_version: String,
    pub environment: String,
    pub revision: i64,
    pub desired_provider: DocumentOcrProvider,
    pub azure_resource_desired: bool,
    pub deprovision_requested: bool,
}

impl DocumentOcrPolicy {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.environment.as_str(), "dev" | "staging" | "prod") { return Err("invalid environment literal"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.revision) { return Err("revision out of bounds"); }
        Ok(())
    }
}

impl DocumentOcrPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_resource_intent(&self) -> Result<DocumentOcrPolicy, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        core::hint::black_box(String::new())
    }
}

