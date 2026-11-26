#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum StewardshipChangePhase {
    #[default]
    Requested,
    Merged,
}

impl StewardshipChangePhase {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Requested => "requested",
            Self::Merged => "merged",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StewardshipChangeEvent {
    pub actor_oid: String,
    pub artifact: String,
    pub affected_agents: Vec<String>,
    pub summary: String,
    pub correlation_id: String,
    pub phase: StewardshipChangePhase,
}

pub const CHANGE_CATEGORY: &str = "operational_alert";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn build_change_notification(mut mp: String, mut event: StewardshipChangeEvent) -> (String, Vec<String>) {
    let agents_label: String = if !(event.affected_agents.clone()).is_empty() { (event.affected_agents.clone()).join(", ") } else { String::from("(none)") };
    let verb: String = String::from("requested\" if event.phase is StewardshipChangePhase.REQUESTED else \"merged");
    (String::new(), Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_change_audit_payload(mut event: StewardshipChangeEvent) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("event"), String::new()), (String::from("actor_oid"), event.actor_oid.clone()), (String::from("artifact"), event.artifact.clone()), (String::from("affected_agents"), (event.affected_agents.clone()).join(",")), (String::from("correlation_id"), event.correlation_id.clone()), (String::from("recorded_at"), String::new()), (String::from("summary"), event.summary.clone())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["CHANGE_CATEGORY", "StewardshipChangeEvent", "StewardshipChangePhase", "build_change_audit_payload", "build_change_notification"];
