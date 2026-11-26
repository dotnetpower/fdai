pub const OBSERVER_REGISTRATIONS_ENV: &str = "FDAI_OBSERVER_REGISTRATIONS_PATH";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CurrentObserverEvidence {
    pub initialized: bool,
}

impl CurrentObserverEvidence {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observing(&self, mut target_ref: String) -> bool {
        self.initialized
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_observer_evidence(mut store: String, mut now: String) -> Option<String> {
    if store.is_empty() {
        return None;
    }
    None
}

