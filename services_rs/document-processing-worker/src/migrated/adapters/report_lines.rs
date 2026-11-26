#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresReportingLineDraftStore {
    pub initialized: bool,
}

impl PostgresReportingLineDraftStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn put(&self, mut artifact: String) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresReportingLineDraftStore"];
