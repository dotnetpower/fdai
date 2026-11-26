#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScheduleRunHistoryItem {
    pub run_id: String,
    pub task_id: String,
    pub scheduled_for: String,
    pub claimed_at: String,
    pub status: String,
    pub attempt: i64,
    pub completed_at: Option<String>,
    pub error_kind: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScheduleRunHistoryPage {
    pub items: Vec<ScheduleRunHistoryItem>,
    pub next_cursor: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ScheduleRunHistoryService {
    pub initialized: bool,
}

impl ScheduleRunHistoryService {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list(&self, mut task_id: String, mut limit: i64, mut cursor: Option<String>, mut status: Option<String>) -> Result<ScheduleRunHistoryPage, &'static str> {
        if (task_id.clone()).is_empty() {
            return Err("schedule history task_id MUST be non-empty");
        }
        if !(((1_i64) <= (limit)) && ((limit) <= (200_i64))) {
            return Err("schedule history limit MUST be in 1 200");
        }
        let mut next_cursor: Option<String> = None;
        Ok(ScheduleRunHistoryPage { next_cursor: next_cursor.clone(), ..Default::default() })
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn item(mut run: String) -> ScheduleRunHistoryItem {
    ScheduleRunHistoryItem::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn encode_cursor(mut scheduled_for: String, mut run_id: String) -> String {
    if scheduled_for.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn decode_cursor(mut value: String) -> Result<(String, String), &'static str> {
    Ok((String::new(), String::new()))
}

pub const PUBLIC_EXPORTS: &[&str] = &["ScheduleRunHistoryItem", "ScheduleRunHistoryPage", "ScheduleRunHistoryService"];
