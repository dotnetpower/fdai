#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProductAddOn {
    #[default]
    ReadOnlyConsole,
    Notifications,
    GovernedExecution,
    EnterpriseIdentityGovernance,
    PolicyAdministration,
}

impl ProductAddOn {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ReadOnlyConsole => "read-only-console",
            Self::Notifications => "notifications",
            Self::GovernedExecution => "governed-execution",
            Self::EnterpriseIdentityGovernance => "enterprise-identity-governance",
            Self::PolicyAdministration => "policy-administration",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AzureObservationRole {
    #[default]
    Reader,
    MonitoringReader,
    LogAnalyticsReader,
    CostManagementReader,
    AksReadOnly,
    EvidenceStoreDataReader,
}

impl AzureObservationRole {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Reader => "Reader",
            Self::MonitoringReader => "Monitoring Reader",
            Self::LogAnalyticsReader => "Log Analytics Reader",
            Self::CostManagementReader => "Cost Management Reader",
            Self::AksReadOnly => "AKS read-only",
            Self::EvidenceStoreDataReader => "Storage Blob Data Reader",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ObservationDataSource {
    #[default]
    Aks,
    AzureMonitor,
    CostManagement,
    EvidenceStore,
    LogAnalytics,
}

impl ObservationDataSource {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Aks => "aks",
            Self::AzureMonitor => "azure-monitor",
            Self::CostManagement => "cost-management",
            Self::EvidenceStore => "evidence-store",
            Self::LogAnalytics => "log-analytics",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObservationReadPermissions {
    pub base_role: String,
    pub selected_sources: Vec<ObservationDataSource>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProductProfile {
    pub schema_version: String,
    pub name: String,
    pub add_ons: Vec<ProductAddOn>,
    pub observation_permissions: Box<ObservationReadPermissions>,
    pub authority_granted: bool,
}

impl ProductProfile {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "fdai.product-profile.v1") { return Err("invalid schema_version literal"); }
        if !matches!(self.name.as_str(), "observation-first") { return Err("invalid name literal"); }
        if self.authority_granted { return Err("authority_granted violated literal bool invariant"); }
        Ok(())
    }
}

impl ObservationReadPermissions {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn canonical_selected_sources(mut value: Vec<ObservationDataSource>) -> Result<Vec<ObservationDataSource>, &'static str> {
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn optional_roles(&self) -> Vec<AzureObservationRole> {
        core::hint::black_box(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn selects_source(&self, mut source: ObservationDataSource) -> bool {
        core::hint::black_box(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn selects(&self, mut role: AzureObservationRole) -> bool {
        core::hint::black_box(false)
    }
}

impl ProductProfile {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn canonical_add_ons(mut value: Vec<ProductAddOn>) -> Result<Vec<ProductAddOn>, &'static str> {
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_add_on_prerequisites(&self) -> Result<ProductProfile, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn selects(&self, mut add_on: ProductAddOn) -> bool {
        core::hint::black_box(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn graph_bindings_selected(&self) -> bool {
        self.selects(Default::default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn approval_bindings_selected(&self) -> bool {
        self.selects(Default::default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn enforcement_bindings_selected(&self) -> bool {
        self.selects(Default::default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn rollback_bindings_selected(&self) -> bool {
        self.selects(Default::default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn privileged_executor_bindings_selected(&self) -> bool {
        self.selects(Default::default())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureObservationRole", "ObservationDataSource", "ObservationReadPermissions", "ProductAddOn", "ProductProfile"];
