pub const MAX_ID: i64 = 256;
pub const MAX_LABEL: i64 = 512;
pub const MAX_CANDIDATES: i64 = 8;
pub const MAX_RECORDS: i64 = 64;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReadInvestigationIntent {
    #[default]
    ResourceState,
    ChangeAttribution,
    ResourceChangeHistory,
    PlatformHealth,
    GuestShutdown,
    NetworkSecurity,
    NetworkPeering,
}

impl ReadInvestigationIntent {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ResourceState => "resource_state",
            Self::ChangeAttribution => "change_attribution",
            Self::ResourceChangeHistory => "resource_change_history",
            Self::PlatformHealth => "platform_health",
            Self::GuestShutdown => "guest_shutdown",
            Self::NetworkSecurity => "network_security",
            Self::NetworkPeering => "network_peering",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReadToolId {
    #[default]
    ResolveResource,
    GetResourceState,
    QueryResourceActivity,
    QueryResourceHealth,
    QueryGuestShutdownEvents,
    QueryNetworkSecurity,
    QueryNetworkPeerings,
}

impl ReadToolId {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ResolveResource => "resolve_resource",
            Self::GetResourceState => "get_resource_state",
            Self::QueryResourceActivity => "query_resource_activity",
            Self::QueryResourceHealth => "query_resource_health",
            Self::QueryGuestShutdownEvents => "query_guest_shutdown_events",
            Self::QueryNetworkSecurity => "query_network_security",
            Self::QueryNetworkPeerings => "query_network_peerings",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ResourceResolutionStatus {
    #[default]
    Matched,
    NotFound,
    Ambiguous,
    Unavailable,
}

impl ResourceResolutionStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Matched => "matched",
            Self::NotFound => "not_found",
            Self::Ambiguous => "ambiguous",
            Self::Unavailable => "unavailable",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EvidenceStatus {
    #[default]
    Matched,
    Ambiguous,
    None,
    Unavailable,
}

impl EvidenceStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Matched => "matched",
            Self::Ambiguous => "ambiguous",
            Self::None => "none",
            Self::Unavailable => "unavailable",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EvidenceFreshness {
    #[default]
    Live,
    Cached,
    Stale,
}

impl EvidenceFreshness {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Live => "live",
            Self::Cached => "cached",
            Self::Stale => "stale",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EvidenceLimitationKind {
    #[default]
    ResultLimit,
    ByteLimit,
    SourceCutoff,
    SourceUnavailable,
    Unauthorized,
    RetentionBoundary,
    Unspecified,
}

impl EvidenceLimitationKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ResultLimit => "result_limit",
            Self::ByteLimit => "byte_limit",
            Self::SourceCutoff => "source_cutoff",
            Self::SourceUnavailable => "source_unavailable",
            Self::Unauthorized => "unauthorized",
            Self::RetentionBoundary => "retention_boundary",
            Self::Unspecified => "unspecified",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ActorKind {
    #[default]
    User,
    ServicePrincipal,
    ManagedIdentity,
    Platform,
    Unknown,
}

impl ActorKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::User => "user",
            Self::ServicePrincipal => "service_principal",
            Self::ManagedIdentity => "managed_identity",
            Self::Platform => "platform",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResourceSelector {
    pub name: String,
    pub scope_ref: String,
    pub resource_type: Option<String>,
    pub resource_group: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResolvedResource {
    pub resource_ref: String,
    pub scope_ref: String,
    pub name: String,
    pub resource_type: String,
    pub resource_group: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResourceCandidate {
    pub resource_ref: String,
    pub name: String,
    pub resource_type: String,
    pub resource_group: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResourceResolution {
    pub status: ResourceResolutionStatus,
    #[allow(clippy::type_complexity)]
    pub resource: Option<Box<ResolvedResource>>,
    pub candidates: Vec<ResourceCandidate>,
    pub detail: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadEvidenceRecord {
    pub occurred_at: String,
    pub status: String,
    pub operation_kind: Option<String>,
    pub actor_ref: Option<String>,
    pub actor_kind: Option<ActorKind>,
    pub correlation_ref: Option<String>,
    pub state: Option<String>,
    pub health_kind: Option<String>,
    pub details: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadEvidenceEnvelope {
    pub status: EvidenceStatus,
    pub authority: String,
    pub resource_ref: String,
    pub observed_at: String,
    pub freshness: EvidenceFreshness,
    pub truncated: bool,
    pub records: Vec<ReadEvidenceRecord>,
    pub evidence_refs: Vec<String>,
    pub limitations: Vec<EvidenceLimitationKind>,
    pub truncation_reason: Option<EvidenceLimitationKind>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadToolLimits {
    pub timeout_seconds: f64,
    pub max_results: i64,
    pub max_output_bytes: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResourceResolutionAttempt {
    pub resolution: Box<ResourceResolution>,
    pub receipt: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadEvidenceAttempt {
    pub tool_id: ReadToolId,
    pub evidence: Box<ReadEvidenceEnvelope>,
    pub receipt: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadLatencySample {
    pub tool_id: ReadToolId,
    pub transport: String,
    pub operation_class: String,
    pub succeeded: bool,
    pub queue_duration_ms: i64,
    pub execution_duration_ms: i64,
    pub recorded_at: String,
    pub correlation_ref: Option<String>,
}

impl ReadLatencySample {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn total_duration_ms(&self) -> i64 {
        (self.queue_duration_ms).saturating_add(self.execution_duration_ms)
    }
}

pub trait ReadLatencyProfileStore {
    fn append(&self, sample: ReadLatencySample) -> String;
}

pub trait ReadInvestigationProvider {
    fn transport(&self) -> String;
}

pub trait ReadInvestigationDiscoveryRefresher {
    fn discover(&self) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn identifier(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn label(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn aware(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ActorKind", "EvidenceFreshness", "EvidenceStatus", "ReadEvidenceEnvelope", "ReadEvidenceAttempt", "ReadEvidenceRecord", "ReadInvestigationDiscoveryRefresher", "ReadInvestigationIntent", "ReadInvestigationProvider", "ReadLatencyProfileStore", "ReadLatencySample", "ReadToolId", "ReadToolLimits", "ResolvedResource", "ResourceCandidate", "ResourceResolution", "ResourceResolutionAttempt", "ResourceResolutionStatus", "ResourceSelector"];
