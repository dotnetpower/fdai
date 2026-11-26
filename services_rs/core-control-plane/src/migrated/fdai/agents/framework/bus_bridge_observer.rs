#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AgentHandlerPhase {
    #[default]
    Started,
    Completed,
    Failed,
}

impl AgentHandlerPhase {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Started => "started",
            Self::Completed => "completed",
            Self::Failed => "failed",
        }
    }
}

pub trait AgentHandlerObserver {
    fn observe(&self, agent: String, topic: String, phase: AgentHandlerPhase, payload: std::collections::BTreeMap<String, String>, error_type: Option<String>) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn notify_handler_observer(mut bridge: String, mut agent: String, mut topic: String, mut phase: AgentHandlerPhase, mut payload: std::collections::BTreeMap<String, String>, mut error_type: Option<String>) {
    if bridge.is_empty() {
        return;
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AgentHandlerObserver", "AgentHandlerPhase", "notify_handler_observer"];
