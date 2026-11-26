#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReadInvestigationProgressKind {
    #[default]
    Planned,
    ResourceResolving,
    ResourceResolved,
    ResourceNotFound,
    ResourceAmbiguous,
    ResourceUnavailable,
    StateQuerying,
    StateCompleted,
    StateUnavailable,
    ActivityQuerying,
    ActivityCompleted,
    ActivityUnavailable,
    HealthQuerying,
    HealthCompleted,
    HealthUnavailable,
    GuestQuerying,
    GuestCompleted,
    GuestUnavailable,
    NetworkSecurityQuerying,
    NetworkSecurityCompleted,
    NetworkSecurityUnavailable,
    NetworkPeeringQuerying,
    NetworkPeeringCompleted,
    NetworkPeeringUnavailable,
    EvidenceCorrelating,
    Delayed,
    Completed,
}

impl ReadInvestigationProgressKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Planned => "investigation.planned",
            Self::ResourceResolving => "resource.resolving",
            Self::ResourceResolved => "resource.resolved",
            Self::ResourceNotFound => "resource.not-found",
            Self::ResourceAmbiguous => "resource.ambiguous",
            Self::ResourceUnavailable => "resource.unavailable",
            Self::StateQuerying => "state.querying",
            Self::StateCompleted => "state.completed",
            Self::StateUnavailable => "state.unavailable",
            Self::ActivityQuerying => "activity.querying",
            Self::ActivityCompleted => "activity.completed",
            Self::ActivityUnavailable => "activity.unavailable",
            Self::HealthQuerying => "health.querying",
            Self::HealthCompleted => "health.completed",
            Self::HealthUnavailable => "health.unavailable",
            Self::GuestQuerying => "guest-log.querying",
            Self::GuestCompleted => "guest-log.completed",
            Self::GuestUnavailable => "guest-log.unavailable",
            Self::NetworkSecurityQuerying => "network-security.querying",
            Self::NetworkSecurityCompleted => "network-security.completed",
            Self::NetworkSecurityUnavailable => "network-security.unavailable",
            Self::NetworkPeeringQuerying => "network-peering.querying",
            Self::NetworkPeeringCompleted => "network-peering.completed",
            Self::NetworkPeeringUnavailable => "network-peering.unavailable",
            Self::EvidenceCorrelating => "evidence.correlating",
            Self::Delayed => "investigation.delayed",
            Self::Completed => "investigation.completed",
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn querying_progress(mut tool_id: String) -> ReadInvestigationProgressKind {
    if tool_id.is_empty() {
        return Default::default();
    }
    Default::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn completed_progress(mut tool_id: String) -> ReadInvestigationProgressKind {
    if tool_id.is_empty() {
        return Default::default();
    }
    Default::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn unavailable_progress(mut tool_id: String) -> ReadInvestigationProgressKind {
    if tool_id.is_empty() {
        return Default::default();
    }
    Default::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ReadInvestigationProgressKind", "completed_progress", "querying_progress", "unavailable_progress"];
