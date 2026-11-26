#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Tier {
    #[default]
    T0,
    T1,
    T2,
}

impl Tier {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::T0 => "t0",
            Self::T1 => "t1",
            Self::T2 => "t2",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Decision {
    #[default]
    Auto,
    Hil,
    Abstain,
    Deny,
}

impl Decision {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Auto => "auto",
            Self::Hil => "hil",
            Self::Abstain => "abstain",
            Self::Deny => "deny",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum IncidentCorrelation {
    #[default]
    Correlate,
    None,
}

impl IncidentCorrelation {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Correlate => "correlate",
            Self::None => "none",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CausalEvidenceGrade {
    #[default]
    Association,
    PredictivePrecedence,
    QuasiExperimental,
    Interventional,
}

impl CausalEvidenceGrade {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Association => "association",
            Self::PredictivePrecedence => "predictive_precedence",
            Self::QuasiExperimental => "quasi_experimental",
            Self::Interventional => "interventional",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Operation {
    #[default]
    Create,
    Update,
    Delete,
    Disable,
    Enable,
    Tag,
    Drop,
    Purge,
    Scale,
    Restart,
    Failover,
    Rotate,
    Revert,
    Attach,
    Detach,
    Quarantine,
}

impl Operation {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Create => "create",
            Self::Update => "update",
            Self::Delete => "delete",
            Self::Disable => "disable",
            Self::Enable => "enable",
            Self::Tag => "tag",
            Self::Drop => "drop",
            Self::Purge => "purge",
            Self::Scale => "scale",
            Self::Restart => "restart",
            Self::Failover => "failover",
            Self::Rotate => "rotate",
            Self::Revert => "revert",
            Self::Attach => "attach",
            Self::Detach => "detach",
            Self::Quarantine => "quarantine",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Severity {
    #[default]
    Critical,
    High,
    Medium,
    Low,
}

impl Severity {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Critical => "critical",
            Self::High => "high",
            Self::Medium => "medium",
            Self::Low => "low",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Category {
    #[default]
    Security,
    Reliability,
    Cost,
    ConfigDrift,
    Compliance,
}

impl Category {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Security => "security",
            Self::Reliability => "reliability",
            Self::Cost => "cost",
            Self::ConfigDrift => "config_drift",
            Self::Compliance => "compliance",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RuleSource {
    #[default]
    Waf,
    AksBaseline,
    Mcsb,
    AzurePolicy,
    AzureAdvisor,
    Cis,
    OpaGatekeeper,
    Checkov,
    Tfsec,
    Kics,
    Trivy,
    KubeBench,
    Custom,
}

impl RuleSource {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Waf => "waf",
            Self::AksBaseline => "aks_baseline",
            Self::Mcsb => "mcsb",
            Self::AzurePolicy => "azure_policy",
            Self::AzureAdvisor => "azure_advisor",
            Self::Cis => "cis",
            Self::OpaGatekeeper => "opa_gatekeeper",
            Self::Checkov => "checkov",
            Self::Tfsec => "tfsec",
            Self::Kics => "kics",
            Self::Trivy => "trivy",
            Self::KubeBench => "kube_bench",
            Self::Custom => "custom",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CheckLogicKind {
    #[default]
    Rego,
    Expression,
}

impl CheckLogicKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Rego => "rego",
            Self::Expression => "expression",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Redistribution {
    #[default]
    Embeddable,
    ReferenceOnly,
}

impl Redistribution {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Embeddable => "embeddable",
            Self::ReferenceOnly => "reference-only",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum BlastRadiusScope {
    #[default]
    Resource,
    ResourceGroup,
    Subscription,
}

impl BlastRadiusScope {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Resource => "resource",
            Self::ResourceGroup => "resource_group",
            Self::Subscription => "subscription",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RollbackKind {
    #[default]
    PrRevert,
    Scripted,
    Pitr,
    SnapshotRestore,
    StateForwardOnly,
}

impl RollbackKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::PrRevert => "pr_revert",
            Self::Scripted => "scripted",
            Self::Pitr => "pitr",
            Self::SnapshotRestore => "snapshot_restore",
            Self::StateForwardOnly => "state_forward_only",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum LinkCardinality {
    #[default]
    OneToOne,
    OneToMany,
    ManyToOne,
    ManyToMany,
}

impl LinkCardinality {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::OneToOne => "one_to_one",
            Self::OneToMany => "one_to_many",
            Self::ManyToOne => "many_to_one",
            Self::ManyToMany => "many_to_many",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ActionInterface {
    #[default]
    ControlPlane,
    DataPlaneMutating,
    IdempotentByKey,
    RateLimited,
    RequiresInventoryFresh,
    GraphTraversalRequired,
    CrossResource,
    AsymmetricRollback,
    RequiresMaintenanceWindow,
}

impl ActionInterface {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ControlPlane => "ControlPlane",
            Self::DataPlaneMutating => "DataPlaneMutating",
            Self::IdempotentByKey => "IdempotentByKey",
            Self::RateLimited => "RateLimited",
            Self::RequiresInventoryFresh => "RequiresInventoryFresh",
            Self::GraphTraversalRequired => "GraphTraversalRequired",
            Self::CrossResource => "CrossResource",
            Self::AsymmetricRollback => "AsymmetricRollback",
            Self::RequiresMaintenanceWindow => "RequiresMaintenanceWindow",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum BlastRadiusComputation {
    #[default]
    StaticEnum,
    GraphDerived,
}

impl BlastRadiusComputation {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::StaticEnum => "static_enum",
            Self::GraphDerived => "graph_derived",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PreconditionKind {
    #[default]
    GraphFreshWithinSeconds,
    LinkExists,
    LinkAbsent,
    NoConflictingOpenActionOnResource,
    MaintenanceWindowActive,
    ResourcePropertyEquals,
    ResourceTagPresent,
}

impl PreconditionKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::GraphFreshWithinSeconds => "graph_fresh_within_seconds",
            Self::LinkExists => "link_exists",
            Self::LinkAbsent => "link_absent",
            Self::NoConflictingOpenActionOnResource => "no_conflicting_open_action_on_resource",
            Self::MaintenanceWindowActive => "maintenance_window_active",
            Self::ResourcePropertyEquals => "resource_property_equals",
            Self::ResourceTagPresent => "resource_tag_present",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum StopConditionKind {
    #[default]
    ErrorRateAbove,
    LatencyP99AboveMs,
    DependentResourceDegraded,
    TimeBoxExceededSeconds,
    ProviderApiErrorStreak,
}

impl StopConditionKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ErrorRateAbove => "error_rate_above",
            Self::LatencyP99AboveMs => "latency_p99_above_ms",
            Self::DependentResourceDegraded => "dependent_resource_degraded",
            Self::TimeBoxExceededSeconds => "time_box_exceeded_seconds",
            Self::ProviderApiErrorStreak => "provider_api_error_streak",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PropertyType {
    #[default]
    StringContract,
    Integer,
    Number,
    Boolean,
    Object,
    Array,
    Datetime,
}

impl PropertyType {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::StringContract => "string",
            Self::Integer => "integer",
            Self::Number => "number",
            Self::Boolean => "boolean",
            Self::Object => "object",
            Self::Array => "array",
            Self::Datetime => "datetime",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TriggerKind {
    #[default]
    RuleViolation,
    OperatorRequest,
    Both,
}

impl TriggerKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::RuleViolation => "rule_violation",
            Self::OperatorRequest => "operator_request",
            Self::Both => "both",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ActionCategory {
    #[default]
    Remediation,
    Ops,
    Governance,
    Tool,
}

impl ActionCategory {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Remediation => "remediation",
            Self::Ops => "ops",
            Self::Governance => "governance",
            Self::Tool => "tool",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Autonomy {
    #[default]
    EnforceAuto,
    EnforceHil,
    ShadowOnly,
}

impl Autonomy {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::EnforceAuto => "enforce_auto",
            Self::EnforceHil => "enforce_hil",
            Self::ShadowOnly => "shadow_only",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ExecutionPath {
    #[default]
    PrNative,
    DirectApi,
    PrManual,
    ToolCall,
}

impl ExecutionPath {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::PrNative => "pr_native",
            Self::DirectApi => "direct_api",
            Self::PrManual => "pr_manual",
            Self::ToolCall => "tool_call",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EnvScope {
    #[default]
    Prod,
    NonProd,
    Any,
}

impl EnvScope {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Prod => "prod",
            Self::NonProd => "non_prod",
            Self::Any => "any",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum IncidentState {
    #[default]
    Open,
    Triaging,
    Mitigated,
    Resolved,
    Closed,
}

impl IncidentState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Open => "open",
            Self::Triaging => "triaging",
            Self::Mitigated => "mitigated",
            Self::Resolved => "resolved",
            Self::Closed => "closed",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum IncidentSeverity {
    #[default]
    Sev1,
    Sev2,
    Sev3,
    Sev4,
    Sev5,
}

impl IncidentSeverity {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Sev1 => "sev1",
            Self::Sev2 => "sev2",
            Self::Sev3 => "sev3",
            Self::Sev4 => "sev4",
            Self::Sev5 => "sev5",
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["Decision", "Mode", "CausalEvidenceGrade", "Operation", "Category", "RuleSource", "CheckLogicKind", "Redistribution", "RollbackKind", "ActionInterface", "BlastRadiusComputation", "PreconditionKind", "StopConditionKind", "PropertyType", "TriggerKind", "ActionCategory", "Autonomy", "CeilingRole", "CEILING_ROLE_RANK", "ExecutionPath", "EnvScope", "IncidentSeverity", "WorkflowTriggerSignalReferenceKind", "WorkflowStepKind"];
