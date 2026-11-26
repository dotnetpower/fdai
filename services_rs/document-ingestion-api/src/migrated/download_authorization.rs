#[derive(Clone, Debug, Default, PartialEq)]
pub struct SourceDownloadAuthorization {
    pub request_id: String,
    pub canonical_receipt: String,
    pub issued_at: String,
    pub expires_at: String,
}

impl SourceDownloadAuthorization {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn receipt_sha256(&self) -> String {
        core::hint::black_box(String::new())
    }
}

pub trait SourceDownloadAuthorizer {
    fn authorize(&self, actor_id: String, actor_groups: std::collections::BTreeSet<String>, version: String) -> SourceDownloadAuthorization;
}

