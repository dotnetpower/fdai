#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RecoveryStrategy {
    #[default]
    Rollback,
    Compensate,
    StateForward,
    Failover,
    Restore,
}

impl RecoveryStrategy {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Rollback => "rollback",
            Self::Compensate => "compensate",
            Self::StateForward => "state_forward",
            Self::Failover => "failover",
            Self::Restore => "restore",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RecoveryPlanStatus {
    #[default]
    Draft,
    Ready,
    Stale,
    Executing,
    Verifying,
    Recovered,
    Escalated,
    Failed,
}

impl RecoveryPlanStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Draft => "draft",
            Self::Ready => "ready",
            Self::Stale => "stale",
            Self::Executing => "executing",
            Self::Verifying => "verifying",
            Self::Recovered => "recovered",
            Self::Escalated => "escalated",
            Self::Failed => "failed",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RecoveryProbeKind {
    #[default]
    FaultAbsent,
    TargetHealthy,
    ObjectivesRecovered,
    IndirectSymptomsAbsent,
    CompensationComplete,
    RecurrenceClear,
}

impl RecoveryProbeKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::FaultAbsent => "fault_absent",
            Self::TargetHealthy => "target_healthy",
            Self::ObjectivesRecovered => "objectives_recovered",
            Self::IndirectSymptomsAbsent => "indirect_symptoms_absent",
            Self::CompensationComplete => "compensation_complete",
            Self::RecurrenceClear => "recurrence_clear",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProbeVerdict {
    #[default]
    Passed,
    Failed,
    Unknown,
}

impl ProbeVerdict {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Passed => "passed",
            Self::Failed => "failed",
            Self::Unknown => "unknown",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RecoveryVerificationOutcome {
    #[default]
    Recovered,
    PartiallyRecovered,
    NotRecovered,
    Unscorable,
}

impl RecoveryVerificationOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Recovered => "recovered",
            Self::PartiallyRecovered => "partially_recovered",
            Self::NotRecovered => "not_recovered",
            Self::Unscorable => "unscorable",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecoveryAction {
    pub action_id: String,
    pub action_type_ref: String,
    pub action_type_version: String,
    pub target_ref: String,
    pub depends_on: Vec<String>,
    pub compensation_action_type_ref: Option<String>,
    pub stop_conditions: Vec<String>,
    pub rollback_ref: Option<String>,
}

impl RecoveryAction {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.action_id.trim().is_empty() { return Err("action_id must be non-empty"); }
        if self.action_type_ref.trim().is_empty() { return Err("action_type_ref must be non-empty"); }
        if self.action_type_version.trim().is_empty() { return Err("action_type_version must be non-empty"); }
        if self.target_ref.trim().is_empty() { return Err("target_ref must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecoveryPlanRecord {
    pub plan_id: String,
    pub strategy: RecoveryStrategy,
    pub status: RecoveryPlanStatus,
    pub workflow_ref: String,
    pub workflow_version: String,
    pub catalog_digest: String,
    pub actions: Vec<RecoveryAction>,
    pub compensation_order: Vec<String>,
    pub impact_envelope_id: String,
    pub recovery_objective_ref: String,
    pub verification_probes: Vec<String>,
    pub direct_target_ids: Vec<String>,
    pub graph_revision: String,
    pub dry_run_receipt: String,
    pub last_rehearsed_at: String,
    pub expires_at: String,
}

impl RecoveryPlanRecord {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.plan_id.trim().is_empty() { return Err("plan_id must be non-empty"); }
        if self.workflow_ref.trim().is_empty() { return Err("workflow_ref must be non-empty"); }
        if self.workflow_version.trim().is_empty() { return Err("workflow_version must be non-empty"); }
        if self.catalog_digest.trim().is_empty() { return Err("catalog_digest must be non-empty"); }
        if self.impact_envelope_id.trim().is_empty() { return Err("impact_envelope_id must be non-empty"); }
        if self.recovery_objective_ref.trim().is_empty() { return Err("recovery_objective_ref must be non-empty"); }
        if self.graph_revision.trim().is_empty() { return Err("graph_revision must be non-empty"); }
        if self.dry_run_receipt.trim().is_empty() { return Err("dry_run_receipt must be non-empty"); }
        if self.last_rehearsed_at.trim().is_empty() { return Err("last_rehearsed_at must be non-empty"); }
        if self.expires_at.trim().is_empty() { return Err("expires_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecoveryReadiness {
    pub ready: bool,
    pub reasons: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecoveryProbeResult {
    pub kind: RecoveryProbeKind,
    pub verdict: ProbeVerdict,
    pub observed_at: String,
    pub evidence_ref: String,
}

impl RecoveryProbeResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        if self.evidence_ref.trim().is_empty() { return Err("evidence_ref must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecoveryVerification {
    pub outcome: RecoveryVerificationOutcome,
    pub probe_results: Vec<RecoveryProbeResult>,
    pub telemetry_complete: bool,
    pub reason: String,
}

impl RecoveryPlanRecord {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_ontology_object(&self) -> String {
        core::hint::black_box(String::new())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ProbeVerdict", "RecoveryAction", "RecoveryPlanRecord", "RecoveryPlanStatus", "RecoveryProbeKind", "RecoveryProbeResult", "RecoveryReadiness", "RecoveryStrategy", "RecoveryVerification", "RecoveryVerificationOutcome"];
