#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SchedulerOutcome {
    #[default]
    Allowed,
    OutsideWindow,
    Frozen,
    OptOut,
    ConcurrencyCap,
}

impl SchedulerOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Allowed => "allowed",
            Self::OutsideWindow => "outside_window",
            Self::Frozen => "frozen",
            Self::OptOut => "opt_out",
            Self::ConcurrencyCap => "concurrency_cap",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ExecutionMode {
    #[default]
    Shadow,
    Enforce,
}

impl ExecutionMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Shadow => "shadow",
            Self::Enforce => "enforce",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RunOutcome {
    #[default]
    NotAllowed,
    IsolationViolation,
    MissingRollbackPath,
    MissingStopCondition,
    InvalidTimeBox,
    MissingProviderRef,
    RunnerNotConfigured,
    ShadowLogged,
    Executed,
    Failed,
    RolledBack,
}

impl RunOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::NotAllowed => "not_allowed",
            Self::IsolationViolation => "isolation_violation",
            Self::MissingRollbackPath => "missing_rollback_path",
            Self::MissingStopCondition => "missing_stop_condition",
            Self::InvalidTimeBox => "invalid_time_box",
            Self::MissingProviderRef => "missing_provider_ref",
            Self::RunnerNotConfigured => "runner_not_configured",
            Self::ShadowLogged => "shadow_logged",
            Self::Executed => "executed",
            Self::Failed => "failed",
            Self::RolledBack => "rolled_back",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MaintenanceWindow {
    pub name: String,
    pub start: String,
    pub end: String,
}

impl MaintenanceWindow {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.name.trim().is_empty() { return Err("name must be non-empty"); }
        if self.start.trim().is_empty() { return Err("start must be non-empty"); }
        if self.end.trim().is_empty() { return Err("end must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FreezePeriod {
    pub name: String,
    pub start: String,
    pub end: String,
}

impl FreezePeriod {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.name.trim().is_empty() { return Err("name must be non-empty"); }
        if self.start.trim().is_empty() { return Err("start must be non-empty"); }
        if self.end.trim().is_empty() { return Err("end must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DrExperiment {
    pub experiment_id: String,
    pub target_resource_ref: String,
    pub target_resource_tags: Vec<String>,
    pub scheduled_at: Option<String>,
    pub provider_ref: Option<String>,
    pub is_production_target: bool,
    pub has_rollback_path: bool,
    pub stop_conditions: Vec<String>,
    pub max_duration_seconds: f64,
}

impl DrExperiment {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.experiment_id.trim().is_empty() { return Err("experiment_id must be non-empty"); }
        if self.target_resource_ref.trim().is_empty() { return Err("target_resource_ref must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DrSchedulerConfig {
    pub max_concurrent_experiments: i64,
    pub opt_out_tag: String,
}

impl DrSchedulerConfig {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.opt_out_tag.trim().is_empty() { return Err("opt_out_tag must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SchedulerDecision {
    pub experiment_id: String,
    pub outcome: SchedulerOutcome,
    pub reasons: Vec<String>,
    pub at: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DrRunResult {
    pub experiment_id: String,
    pub outcome: RunOutcome,
    pub decision: Box<SchedulerDecision>,
    pub handle: Option<String>,
    pub status: Option<String>,
    pub error: Option<String>,
    pub reasons: Vec<String>,
    pub at: Option<String>,
}

impl MaintenanceWindow {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn contains(&self, mut moment: String) -> bool {
        ((self.start.clone()) <= (moment.clone())) && ((moment.clone()) <= (self.end.clone()))
    }
}

impl FreezePeriod {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn contains(&self, mut moment: String) -> bool {
        ((self.start.clone()) <= (moment.clone())) && ((moment.clone()) <= (self.end.clone()))
    }
}

