use std::collections::BTreeMap;
pub const MAX_RELEASE_ID_LENGTH: i64 = 64;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Health {
    #[default]
    Healthy,
    Degraded,
    Unhealthy,
    Unknown,
}

impl Health {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Healthy => "healthy",
            Self::Degraded => "degraded",
            Self::Unhealthy => "unhealthy",
            Self::Unknown => "unknown",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OutcomeKind {
    #[default]
    Issued,
    Unchanged,
    Waiting,
    NoEligibleRelease,
    UpToDate,
    NoManagedEntity,
}

impl OutcomeKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Issued => "issued",
            Self::Unchanged => "unchanged",
            Self::Waiting => "waiting",
            Self::NoEligibleRelease => "no-eligible-release",
            Self::UpToDate => "up-to-date",
            Self::NoManagedEntity => "no-managed-entity",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PlanStatus {
    #[default]
    Open,
    Superseded,
}

impl PlanStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Open => "open",
            Self::Superseded => "superseded",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DailyWindow {
    pub start: String,
    pub duration: String,
    pub timezone: String,
    pub allows_downtime: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Settings {
    pub channel: String,
    pub version_range: String,
    pub region: String,
    pub allowed_regions: Vec<String>,
    pub windows: Vec<DailyWindow>,
    pub plan_duration: String,
    pub fencing_generation: i64,
    pub product: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Configuration {
    pub schema: BTreeMap<String, String>,
    pub environment: BTreeMap<String, String>,
    #[allow(clippy::type_complexity)]
    pub entity_overrides: Vec<BTreeMap<String, String>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EntityState {
    pub release_id: Option<String>,
    pub artifact_digests: Vec<String>,
    pub health: Health,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportedState {
    pub digest: String,
    pub schema_revision: i64,
    pub entities: BTreeMap<String, EntityState>,
    pub observed_at: String,
    #[allow(clippy::type_complexity)]
    pub available_artifact_digests: Option<Vec<String>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IssuedPlan {
    pub plan_id: String,
    pub sequence: i64,
    pub plan_type: String,
    pub target_release_id: String,
    pub source_state_digest: String,
    pub configuration_digest: String,
    pub hub_key_id: String,
    pub entity_ids: Vec<String>,
    pub expires_at: String,
    pub signed_payload: Vec<u8>,
    pub signature: Vec<u8>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Installation {
    pub installation_id: String,
    pub settings: Box<Settings>,
    pub entities: Vec<String>,
    pub configuration: Box<Configuration>,
    pub reported: Box<ReportedState>,
    pub suppressions: Vec<String>,
    pub commands: Vec<String>,
    pub last_sequence: i64,
    #[allow(clippy::type_complexity)]
    pub open_plan: Option<Box<IssuedPlan>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CandidateCheck {
    pub release_id: String,
    pub blocks: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Issued {
    pub plan: String,
    pub checks: Vec<CandidateCheck>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Unchanged {
    pub plan: Box<IssuedPlan>,
    pub checks: Vec<CandidateCheck>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Waiting {
    pub release_id: String,
    pub checks: Vec<CandidateCheck>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct NoEligibleRelease {
    pub checks: Vec<CandidateCheck>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct UpToDate {
    pub checks: Vec<CandidateCheck>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct NoManagedEntity {
    pub checks: Vec<CandidateCheck>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Evaluation {
    pub outcome: OutcomeKind,
    pub target_release_id: Option<String>,
    pub plan_id: Option<String>,
    pub checks: Vec<CandidateCheck>,
    pub evaluated_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PendingEnrollment {
    pub installation: Box<Installation>,
    pub installation_key_id: String,
    pub requested_at: String,
    pub requested_by: Option<String>,
    pub requested_via: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InstallationOverview {
    pub installation: Box<Installation>,
    #[allow(clippy::type_complexity)]
    pub last_evaluation: Option<Box<Evaluation>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PlanEventRecord {
    pub kind: String,
    pub recorded_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PlanRecord {
    pub plan: Box<IssuedPlan>,
    pub status: PlanStatus,
    pub events: Vec<PlanEventRecord>,
    pub evaluations: Vec<Evaluation>,
}

pub const SHA256_HEX: &str = "[0-9a-f]{64}";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StaleStateError {
    pub message: String,
}

impl StaleStateError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for StaleStateError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for StaleStateError {}

impl DailyWindow {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn around(&self, mut now: String) -> Vec<String> {
        if now.is_empty() {
            return Vec::new();
        }
        Vec::new()
    }
}

impl Settings {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn plan_duration_minutes(&self) -> i64 {
        0_i64
    }
}

impl Configuration {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        core::hint::black_box(String::new())
    }
}

impl ReportedState {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn current_release(&self, mut entity_ids: std::collections::BTreeSet<String>) -> Option<String> {
        let mut releases: Vec<String> = Vec::<String>::new();
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn artifact_digests(&self) -> std::collections::BTreeSet<String> {
        std::collections::BTreeSet::new()
    }
}

impl IssuedPlan {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_signed(mut plan: String) -> String {
        if plan.is_empty() {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn held_by(&self, mut suppressions: Vec<String>, mut now: String) -> bool {
        if suppressions.is_empty() {
            return false;
        }
        false
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn still_valid_for(&self, mut plan: String, mut now: String) -> bool {
        if plan.is_empty() {
            return false;
        }
        false
    }
}

impl Installation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn with_command(&self, mut command: String, mut now: String) -> String {
        if command.is_empty() {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn with_reported(&self, mut state: ReportedState) -> Result<String, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn suppressed(&self, mut window: String, mut now: String) -> Result<String, &'static str> {
        if !(self.is_scope(String::new())) {
            return Err("unknown suppression scope: window.scoper");
        }
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn lifted(&self, mut scope: String, mut now: String) -> Result<String, &'static str> {
        let current: Vec<String> = self.unexpired(now.clone());
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn unexpired(&self, mut now: String) -> Vec<String> {
        if now.is_empty() {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_scope(&self, mut scope: String) -> bool {
        if (scope.clone()) == (String::from("installation")) {
            return true;
        }
        false
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn managed_entity_ids(&self) -> std::collections::BTreeSet<String> {
        std::collections::BTreeSet::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn current_release(&self) -> Option<String> {
        core::hint::black_box(None)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn maintenance_windows(&self, mut now: String) -> Vec<String> {
        if now.is_empty() {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn overall_health(&self) -> Option<Health> {
        core::hint::black_box(None)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn next_window(&self, mut now: String) -> Option<String> {
        if now.is_empty() {
            return None;
        }
        None
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn utc_now() -> String {
    core::hint::black_box(String::new())
}

