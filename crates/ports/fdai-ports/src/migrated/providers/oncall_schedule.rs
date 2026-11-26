#[derive(Clone, Debug, Default, PartialEq)]
pub struct OnCallShift {
    pub rotation: String,
    pub primary_oid: String,
    pub secondary_oid: Option<String>,
    pub start: String,
    pub until: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct OnCallScheduleError {
    pub message: String,
}

impl OnCallScheduleError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for OnCallScheduleError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for OnCallScheduleError {}

pub trait OnCallSchedule {
    fn current(&self, rotation: String, at: String) -> Option<OnCallShift>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StaticOnCallSchedule {
    pub initialized: bool,
}

impl StaticOnCallSchedule {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn current(&self, mut rotation: String, mut at: String) -> Option<OnCallShift> {
        if !self.initialized {
            return None;
        }
        None
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["OnCallSchedule", "OnCallScheduleError", "OnCallShift", "StaticOnCallSchedule"];
