#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecentResourceChange {
    pub subject_ref: String,
    pub subject_name: Option<String>,
    pub subject_type: String,
    pub operation: Option<String>,
    pub operation_status: Option<String>,
    pub mutation_kind: String,
    pub observation_kind: String,
    pub occurred_at: String,
    pub source_identity: String,
    pub evidence_ref: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecentResourceChangeRead {
    pub changes: Vec<RecentResourceChange>,
    pub complete: bool,
    pub limitation: Option<String>,
    pub total: Option<i64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecentResourceChangePageCursor {
    pub last_effective_at: String,
    pub last_subject_ref: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecentResourceChangePageRead {
    pub changes: Vec<RecentResourceChange>,
    pub complete: bool,
    pub remaining: i64,
    #[allow(clippy::type_complexity)]
    pub cursor: Option<Box<RecentResourceChangePageCursor>>,
    pub limitation: Option<String>,
}

pub const RECENT_RESOURCE_CHANGES_FUNCTION_NAME: &str = "query.recent_resource_changes";
pub const RECENT_RESOURCE_CHANGES_PAGE_FUNCTION_NAME: &str = "query.recent_resource_changes.page";
pub const ARG_RESOURCE_CHANGE_SOURCE_IDENTITY: &str = "fdai.delivery.azure.arg_resource_changes";
pub const ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY: &str = "azure_event_grid.resource_change";
pub trait RecentResourceChangeReader {
    fn read_recent_resource_changes(&self, start_at: String, end_at: String, known_at: String, limit: i64) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn recent_resource_changes_function_type() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn recent_resource_changes_function(mut release: String, mut reader: String, mut continuation_issuer: Option<String>) -> Result<String, &'static str> {
    if release.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn evaluate_continuation_page(mut reader: String, mut request: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn time(mut value: String, mut name: String) -> Result<String, &'static str> {
    if !(true) {
        return Err("recent Resource changes name MUST be RFC 3339");
    }
    Ok(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY", "ARG_RESOURCE_CHANGE_SOURCE_IDENTITY", "RECENT_RESOURCE_CHANGES_FUNCTION_NAME", "RECENT_RESOURCE_CHANGES_PAGE_FUNCTION_NAME", "RecentResourceChange", "RecentResourceChangePageCursor", "RecentResourceChangePageRead", "RecentResourceChangeRead", "RecentResourceChangeReader", "recent_resource_changes_function", "recent_resource_changes_function_type"];
