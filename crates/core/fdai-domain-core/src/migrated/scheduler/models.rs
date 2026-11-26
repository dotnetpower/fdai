use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ScheduleKind {
    #[default]
    Interval,
    OneShot,
    Cron,
    EventExit,
}

impl ScheduleKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Interval => "interval",
            Self::OneShot => "one-shot",
            Self::Cron => "cron",
            Self::EventExit => "event-exit",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScheduledRunIsolationProfile {
    pub profile_id: String,
    pub max_session_seconds: i64,
    pub max_context_chars: i64,
    pub max_tool_calls: i64,
    pub allowed_tool_ids: Vec<String>,
    pub command_sandbox_profile_id: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScheduledTask {
    pub task_id: String,
    pub name: String,
    pub interval_seconds: f64,
    pub event_type: String,
    pub created_by: String,
    pub event_payload: BTreeMap<String, String>,
    pub resource_ref: Option<String>,
    pub enabled: bool,
    pub start_at: Option<String>,
    pub last_run: Option<String>,
    pub cron_expression: Option<String>,
    pub schedule_kind: Option<ScheduleKind>,
    pub timezone: String,
    pub exit_event_type: Option<String>,
    pub exit_observed_at: Option<String>,
    pub isolation_profile: Box<ScheduledRunIsolationProfile>,
    pub continuation_mode: String,
    pub continuation_origin: Option<String>,
}

impl ScheduledTask {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn kind(&self) -> ScheduleKind {
        core::hint::black_box(Default::default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn with_last_run(&self, mut at: String) -> ScheduledTask {
        if at.is_empty() {
            return Default::default();
        }
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn with_exit_observed(&self, mut at: String) -> Result<ScheduledTask, &'static str> {
        if at.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn valid_interval_seconds(mut value: String) -> bool {
    if (false) || (!(true)) {
        return false;
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["ScheduleKind", "ScheduledRunIsolationProfile", "ScheduledTask"];
