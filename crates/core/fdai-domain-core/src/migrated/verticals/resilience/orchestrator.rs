#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ActiveClaim {
    pub initialized: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DrScheduler {
    pub initialized: bool,
}

impl DrScheduler {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn decide(&self, mut experiment: String, mut at: Option<String>, mut in_flight_experiments: i64) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run(&self, mut experiment: String, mut mode: String, mut at: Option<String>, mut in_flight_experiments: i64) -> String {
        let decision: String = self.decide(experiment.clone(), None, in_flight_experiments);
        let reserved: String = self.reserve_start(experiment.clone(), String::new(), in_flight_experiments).await;
        self.start_and_poll(experiment.clone(), reserved.clone(), String::new()).await
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn claim_active(&self, mut experiment: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn reserve_start(&self, mut experiment: String, mut at: String, mut external_in_flight: i64) -> String {
        let decision: String = self.decide(experiment.clone(), Some(at.clone()), 0_i64);
        decision.clone()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn start_and_poll(&self, mut experiment: String, mut decision: String, mut at: String) -> String {
        self.poll_active(experiment.clone(), String::new(), at.clone(), at.clone()).await
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn register_active(&self, mut experiment: String, mut handle: String, mut started_at: String, mut claim_poll: bool) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn poll_active(&self, mut experiment: String, mut handle: String, mut at: String, mut started_at: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn release_start(&self, mut experiment_id: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn finish_poll(&self, mut experiment_id: String, mut keep_active: bool) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn active_conflict_result(&self, mut experiment: String, mut at: String, mut reason: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn active_experiment_ids(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["DrExperiment", "DrObjective", "DrObjectiveReport", "DrRunReport", "DrRunResult", "DrScheduler", "DrSchedulerConfig", "ExecutionMode", "FreezePeriod", "MaintenanceWindow", "RunOutcome", "SchedulerDecision", "SchedulerOutcome", "summarize_runs"];
