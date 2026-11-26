pub const DEFAULT_EVENT_HANDLING_TIMEOUT_SECONDS: f64 = 5.0;
pub const DEFAULT_PUBLISH_TIMEOUT_SECONDS: f64 = 2.0;
pub trait ReconciliationLineageMaterializer {
    fn project(&self, outcome: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PublishTimeoutEventBus {
    pub initialized: bool,
}

impl PublishTimeoutEventBus {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn publish(&self, mut topic: String, mut key: String, mut payload: std::collections::BTreeMap<String, String>) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn subscribe(&self, mut topic: String, mut group_id: String) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn dead_letter(&self, mut topic: String, mut key: String, mut payload: std::collections::BTreeMap<String, String>, mut reason: String) {
        if !self.initialized {
            return;
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EffectReconciliationWorker {
    pub initialized: bool,
}

impl EffectReconciliationWorker {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn handle_payload(&self, mut payload: std::collections::BTreeMap<String, String>) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run_subscriber(&self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn publish_pending_once(&self) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn drain_pending(&self, mut limit: i64) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_aware_clock(mut now: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["EffectReconciliationWorker", "PublishTimeoutEventBus"];
