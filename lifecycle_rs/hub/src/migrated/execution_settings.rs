#[derive(Clone, Debug, Default, PartialEq)]
pub struct WindowRequest {
    pub start: String,
    pub duration_minutes: f64,
    pub timezone: String,
    pub allows_downtime: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SettingsChangeRequest {
    pub request_id: String,
    pub expected_settings_digest: String,
    pub reason_code: String,
    pub confirmation: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExecutionSettingsRequest {
    pub windows: Vec<WindowRequest>,
    pub plan_duration_minutes: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ApplicationBindingRequest {
    pub product: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ExecutionSettingsError {
    pub message: String,
}

impl ExecutionSettingsError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ExecutionSettingsError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ExecutionSettingsError {}

impl WindowRequest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_window(&self) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn validate_window(&self) -> WindowRequest {
        core::hint::black_box(Default::default())
    }
}

impl SettingsChangeRequest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        core::hint::black_box(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn settings_digest(mut settings: String) -> String {
    if settings.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn settings_record(mut settings: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("settings_digest"), settings_digest(settings.clone())), (String::from("product"), String::new()), (String::from("windows"), String::new()), (String::from("plan_duration_minutes"), String::new())])
}

