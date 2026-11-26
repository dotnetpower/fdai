pub trait RetentionMetadataStore {
    fn list_due_temporary_versions(&self, now: String, limit: i64) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DocumentRetentionReconciler {
    pub initialized: bool,
}

impl DocumentRetentionReconciler {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run_once(&self) -> Result<i64, &'static str> {
        let mut submitted: i64 = 0_i64;
        Ok(submitted)
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["DocumentRetentionReconciler", "RetentionMetadataStore"];
