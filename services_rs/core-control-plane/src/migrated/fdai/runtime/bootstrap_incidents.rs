use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct IncidentNotificationReplayWorker {
    pub notifier: String,
    #[allow(clippy::type_complexity)]
    pub entries: Vec<BTreeMap<String, String>>,
    pub retry_interval_seconds: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IncidentRuntime {
    pub registry: String,
    #[allow(clippy::type_complexity)]
    pub entries: Vec<BTreeMap<String, String>>,
    pub notification_replay_worker: Box<IncidentNotificationReplayWorker>,
    pub intervention_binding: String,
    pub creation_binding: String,
    pub open_incident_candidate: String,
    pub resolve_verified_incident: String,
    pub observe_tool_receipt: String,
    pub notification_receipt_applier: String,
}

pub const INCIDENT_EPISODE_BINDING_PREFIX: &str = "incident:episode-binding:v1:";
pub trait ReplayIncidentNotifier {
    fn notify(&self, notice: String) -> String;
}

impl IncidentNotificationReplayWorker {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn run(&self, mut stop: String) -> Result<(), &'static str> {
        if (self.retry_interval_seconds) <= (0.0) {
            return Err("incident notification replay retry interval MUST be positive");
        }
        Ok(())
    }
}

impl IncidentRuntime {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn bind_projection(&self, mut store: String) {
        if store.is_empty() {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn with_pantheon(&self, mut pantheon: Option<String>) -> String {
        let required: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("Huginn"), String::from("Forseti"), String::from("Saga")]);
        String::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn build_incident_runtime(mut state_store: String, mut runtime_values: std::collections::BTreeMap<String, String>, mut http_client: Option<String>, mut notifier_builder: String) -> Result<IncidentRuntime, &'static str> {
    let notification_replay_worker: IncidentNotificationReplayWorker = IncidentNotificationReplayWorker::default();
    Ok(IncidentRuntime { notification_replay_worker: Box::new(notification_replay_worker.clone()), ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["IncidentNotifierBuilder", "IncidentNotificationReplayWorker", "IncidentRuntime", "IncidentCreationConsumerBinding", "IncidentInterventionConsumerBinding", "ObserveToolReceipt", "OpenIncidentCandidate", "ReplayIncidentNotifier", "build_incident_runtime"];
