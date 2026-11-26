pub trait FaultInjector {
    fn fault_type(&self) -> String;
    fn inject(&self, target: String, params: std::collections::BTreeMap<String, String>);
    fn stop(&self, target: String);
}

pub trait MutationScopedInjector {
    fn mutated_resources(&self, target: String) -> Vec<String>;
}

pub trait SignalProbe {
    fn observed(&self, signal: String, targets: Vec<String>) -> bool;
}

pub trait TimedSignalProbe {
    fn first_observed_at(&self, signal: String, targets: Vec<String>, window_start: String, window_end: String) -> Option<String>;
}

pub trait ExperimentRecorder {
    fn record(&self, result: String);
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ShadowFaultInjector {
    pub initialized: bool,
}

impl ShadowFaultInjector {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn fault_type(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn inject(&self, mut target: String, mut params: std::collections::BTreeMap<String, String>) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn stop(&self, mut target: String) {
        if !self.initialized {
            return;
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DetectionOnlyInjector {
    pub initialized: bool,
}

impl DetectionOnlyInjector {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn fault_type(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn inject(&self, mut target: String, mut params: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
        Err("detection-only scenarios MUST NOT inject")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn stop(&self, mut target: String) -> Result<(), &'static str> {
        Err("detection-only scenarios MUST NOT roll back a mutation")
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NoSignalProbe {
    pub initialized: bool,
}

impl NoSignalProbe {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observed(&self, mut signal: String, mut targets: Vec<String>) -> bool {
        self.initialized
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryExperimentRecorder {
    pub initialized: bool,
}

impl InMemoryExperimentRecorder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn record(&self, mut result: String) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["DetectionOnlyInjector", "ExperimentRecorder", "FaultInjector", "InMemoryExperimentRecorder", "MutationScopedInjector", "NoSignalProbe", "ShadowFaultInjector", "SignalProbe", "TimedSignalProbe"];
