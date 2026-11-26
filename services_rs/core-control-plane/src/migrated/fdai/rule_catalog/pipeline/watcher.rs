#[derive(Clone, Debug, Default, PartialEq)]
pub struct SourceWatcher {
    pub snapshot_root: String,
}

pub const SUCCESS_RECEIPT: &str = "COLLECTION_SUCCESS.json";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct WatcherError {
    pub message: String,
}

impl WatcherError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for WatcherError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for WatcherError {}

impl SourceWatcher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_due(&self, mut manifest: String, mut now: String) -> bool {
        let last: Option<String> = self.last_collected_at(String::new());
        let Some(mut last) = last.clone() else { return true; };
        false
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn interval_for(mut cadence: String) -> Result<Option<String>, &'static str> {
        if cadence.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn last_collected_at(&self, mut source_id: String) -> Option<String> {
        let mut latest: Option<String> = None;
        latest.clone()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["SourceWatcher", "WatcherError"];
