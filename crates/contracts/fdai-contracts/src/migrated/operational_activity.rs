#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OperationalActivityKind {
    #[default]
    InventoryScan,
    InventoryOntologyProjection,
    CurrentStateRead,
    Observation,
    AssuranceTwinPosture,
}

impl OperationalActivityKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::InventoryScan => "inventory.scan",
            Self::InventoryOntologyProjection => "inventory.ontology-projection",
            Self::CurrentStateRead => "current-state.read",
            Self::Observation => "observation",
            Self::AssuranceTwinPosture => "assurance-twin.posture",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ObservationDomain {
    #[default]
    Inventory,
    ActivityLog,
    ResourceHealth,
    ServiceHealth,
    Metrics,
    Logs,
    GuestLogs,
    NetworkConfig,
    Cost,
    Recovery,
}

impl ObservationDomain {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Inventory => "inventory",
            Self::ActivityLog => "activity-log",
            Self::ResourceHealth => "resource-health",
            Self::ServiceHealth => "service-health",
            Self::Metrics => "metrics",
            Self::Logs => "logs",
            Self::GuestLogs => "guest-logs",
            Self::NetworkConfig => "network-config",
            Self::Cost => "cost",
            Self::Recovery => "recovery",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OperationalActivityStatus {
    #[default]
    Started,
    Completed,
    Failed,
    Superseded,
    Degraded,
}

impl OperationalActivityStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Started => "started",
            Self::Completed => "completed",
            Self::Failed => "failed",
            Self::Superseded => "superseded",
            Self::Degraded => "degraded",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OperationalFreshness {
    #[default]
    Fresh,
    Stale,
    Unavailable,
    Unknown,
}

impl OperationalFreshness {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Fresh => "fresh",
            Self::Stale => "stale",
            Self::Unavailable => "unavailable",
            Self::Unknown => "unknown",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OperationalActivitySummaryKey {
    #[default]
    InventoryCollection,
    OntologyProjection,
    CurrentStateObservation,
    SourceObservation,
    AssurancePosture,
}

impl OperationalActivitySummaryKey {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::InventoryCollection => "inventory_collection",
            Self::OntologyProjection => "ontology_projection",
            Self::CurrentStateObservation => "current_state_observation",
            Self::SourceObservation => "source_observation",
            Self::AssurancePosture => "assurance_posture",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OperationalActivityScopeClass {
    #[default]
    ConfiguredEstate,
    SourceDomain,
    Investigation,
    ChangeReview,
}

impl OperationalActivityScopeClass {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ConfiguredEstate => "configured-estate",
            Self::SourceDomain => "source-domain",
            Self::Investigation => "investigation",
            Self::ChangeReview => "change-review",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OperationalActivityResultState {
    #[default]
    Measured,
    NotRecorded,
    Unavailable,
}

impl OperationalActivityResultState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Measured => "measured",
            Self::NotRecorded => "not-recorded",
            Self::Unavailable => "unavailable",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OperationalActivityResultUnit {
    #[default]
    EvidenceItems,
    Resources,
    Records,
    Signals,
    Receipts,
}

impl OperationalActivityResultUnit {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::EvidenceItems => "evidence-items",
            Self::Resources => "resources",
            Self::Records => "records",
            Self::Signals => "signals",
            Self::Receipts => "receipts",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AgentOperationalActivity {
    pub r#type: String,
    pub schema_version: String,
    pub activity_id: String,
    pub activity_instance_id: Option<String>,
    pub idempotency_key: String,
    pub kind: OperationalActivityKind,
    pub status: OperationalActivityStatus,
    pub owner_agent: String,
    pub producer: String,
    pub observation_domain: Option<ObservationDomain>,
    pub observed_at: String,
    pub source: String,
    pub freshness: OperationalFreshness,
    pub evidence_count: i64,
    pub duration_ms: Option<i64>,
    pub correlation_id: Option<String>,
    pub reason_codes: Vec<String>,
    pub summary_key: Option<OperationalActivitySummaryKey>,
    pub scope_class: Option<OperationalActivityScopeClass>,
    pub target_count: Option<i64>,
    pub result_state: Option<OperationalActivityResultState>,
    pub result_count: Option<i64>,
    pub result_unit: Option<OperationalActivityResultUnit>,
    pub source_cutoff: Option<String>,
    pub started_at: Option<String>,
    pub completed_at: Option<String>,
    pub execution_authority: bool,
}

impl AgentOperationalActivity {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.r#type.as_str(), "agent.operational-activity") { return Err("invalid type literal"); }
        if !matches!(self.schema_version.as_str(), "1.0.0" | "1.1.0" | "1.2.0" | "1.3.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.owner_agent.as_str(), "Huginn" | "Heimdall" | "Njord" | "Freyr" | "Vidar") { return Err("invalid owner_agent literal"); }
        if !matches!(self.producer.as_str(), "inventory-sync-job" | "core-control-plane" | "observation-campaign-job" | "assurance-twin") { return Err("invalid producer literal"); }
        if !(0_i64..=1000000_i64).contains(&self.evidence_count) { return Err("evidence_count out of bounds"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub const OBSERVATION_REASON_CODE: &str = "^[a-z][a-z0-9_]{0,127}$";
impl AgentOperationalActivity {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn serialize_versioned(&self, mut handler: String) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_ownership(&self) -> Result<AgentOperationalActivity, &'static str> {
        let _ = self.validate_presentation().unwrap_or_else(|_| ());
        if ((((self.reason_codes.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((self.reason_codes.clone()).len() as i64)) {
            return Err("reason_codes MUST NOT contain duplicates");
        }
        Ok(self.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn validate_presentation(&self) -> Result<(), &'static str> {
        if (self.schema_version.clone()) != (String::from("1.3.0")) {
            return Ok(());
        }
        if self.activity_instance_id.is_none() {
            return Err("schema 1.3.0 activity_instance_id MUST be present");
        }
        if (self.summary_key.is_none()) || ((self.scope_class.is_none()) || (self.result_state.is_none())) {
            return Err("schema 1.3.0 presentation classification MUST be present");
        }
        if (self.started_at.is_some()) && ((self.completed_at.is_some()) && (((self.completed_at.clone()).unwrap_or_default()) < ((self.started_at.clone()).unwrap_or_default()))) {
            return Err("completed_at MUST NOT precede started_at");
        }
        Ok(())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AgentOperationalActivity", "ObservationDomain", "OperationalActivityKind", "OperationalActivityResultState", "OperationalActivityResultUnit", "OperationalActivityScopeClass", "OperationalActivityStatus", "OperationalActivitySummaryKey", "OperationalFreshness"];
