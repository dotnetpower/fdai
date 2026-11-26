use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RequirementKind {
    #[default]
    StopCondition,
    RollbackDefined,
    BlastRadiusBounded,
    ApproverAssigned,
    NotifyChannel,
}

impl RequirementKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::StopCondition => "stop_condition",
            Self::RollbackDefined => "rollback_defined",
            Self::BlastRadiusBounded => "blast_radius_bounded",
            Self::ApproverAssigned => "approver_assigned",
            Self::NotifyChannel => "notify_channel",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PlanStatus {
    #[default]
    Draft,
    Ready,
    Active,
    Retired,
}

impl PlanStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Draft => "draft",
            Self::Ready => "ready",
            Self::Active => "active",
            Self::Retired => "retired",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PlanRequirement {
    pub kind: RequirementKind,
    pub description: String,
    pub satisfied: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResponseStep {
    pub step_id: String,
    pub action_ref: String,
    pub description: String,
}

impl ResponseStep {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.step_id.trim().is_empty() { return Err("step_id must be non-empty"); }
        if self.action_ref.trim().is_empty() { return Err("action_ref must be non-empty"); }
        if self.description.trim().is_empty() { return Err("description must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResponsePlan {
    pub plan_id: String,
    pub name: String,
    pub trigger_signal: String,
    pub steps: Vec<ResponseStep>,
    pub requirements: Vec<PlanRequirement>,
    pub approver_role: String,
    pub notify_channels: Vec<String>,
    pub created_by: String,
    pub created_at: String,
    pub status: PlanStatus,
    pub similar_incident_refs: Vec<String>,
    pub metadata: BTreeMap<String, String>,
}

impl ResponsePlan {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.plan_id.trim().is_empty() { return Err("plan_id must be non-empty"); }
        if self.name.trim().is_empty() { return Err("name must be non-empty"); }
        if self.trigger_signal.trim().is_empty() { return Err("trigger_signal must be non-empty"); }
        if self.approver_role.trim().is_empty() { return Err("approver_role must be non-empty"); }
        if self.created_by.trim().is_empty() { return Err("created_by must be non-empty"); }
        if self.created_at.trim().is_empty() { return Err("created_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadinessReport {
    pub plan_id: String,
    pub ready: bool,
    pub unmet: Vec<RequirementKind>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HistoricalIncident {
    pub incident_ref: String,
    pub signals: Vec<String>,
    pub resolved_by_action: Option<String>,
}

impl HistoricalIncident {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.incident_ref.trim().is_empty() { return Err("incident_ref must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PretestReport {
    pub plan_id: String,
    pub matched: i64,
    pub total: i64,
    pub unmatched_incident_refs: Vec<String>,
}

impl PretestReport {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.plan_id.trim().is_empty() { return Err("plan_id must be non-empty"); }
        Ok(())
    }
}

impl ReadinessReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn blocked(&self) -> bool {
        !(self.ready)
    }
}

impl PretestReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn coverage(&self) -> f64 {
        if (self.total) == (0_i64) {
            return 0.0;
        }
        0.0_f64
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["HistoricalIncident", "PlanRequirement", "PlanStatus", "PretestReport", "ReadinessReport", "RequirementKind", "ResponsePlan", "ResponseStep"];
