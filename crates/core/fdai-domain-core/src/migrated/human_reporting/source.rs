#[derive(Clone, Debug, Default, PartialEq)]
pub struct StateStoreReportingLineDraftReader {
    pub store: String,
}

pub trait ReportingLineDraftReader {
    fn get(&self, upload_id: String) -> String;
}

impl StateStoreReportingLineDraftReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get(&self, mut upload_id: String) -> Result<String, &'static str> {
        if upload_id.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ReportingLineDraftReader", "StateStoreReportingLineDraftReader"];
