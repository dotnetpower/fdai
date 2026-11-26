#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TrialStatus {
    #[default]
    Active,
    Expired,
    ClockBlocked,
}

impl TrialStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Active => "trial-active",
            Self::Expired => "trial-expired",
            Self::ClockBlocked => "trial-clock-blocked",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TrialRecord {
    pub installation_binding: String,
    pub deployment_binding: String,
    pub activated_at: String,
    pub last_observed_at: String,
    pub revision: i64,
    pub clock_blocked: bool,
}

pub const DIGEST: &str = "[0-9a-f]{64}";
impl TrialRecord {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn expires_at(&self) -> Result<String, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn status(&self) -> TrialStatus {
        core::hint::black_box(Default::default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn observe(&self, mut now: String) -> TrialRecord {
        if now.is_empty() {
            return Default::default();
        }
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("schema_version"), String::from("fdai.trial-record.v1")), (String::from("installation_binding"), self.installation_binding.clone()), (String::from("deployment_binding"), self.deployment_binding.clone()), (String::from("activated_at"), String::new()), (String::from("last_observed_at"), String::new()), (String::from("revision"), String::new()), (String::from("clock_blocked"), String::new())])
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_mapping(mut value: std::collections::BTreeMap<String, String>) -> Result<TrialRecord, &'static str> {
        let expected: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("schema_version"), String::from("installation_binding"), String::from("deployment_binding"), String::from("activated_at"), String::from("last_observed_at"), String::from("revision"), String::from("clock_blocked")]);
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_utc(mut moment: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

