pub trait OperationalProofReader {
    fn newest_admissions(&self, lookup_digest: String, pins_digests: std::collections::BTreeSet<String>, limit: i64) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct OperationalEvidenceAdmissionProvider {
    pub initialized: bool,
}

impl OperationalEvidenceAdmissionProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn admit(&self, mut evidence_digest: String, mut scope_digest: String, mut purpose_id: String, mut source_revision: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn outcome(&self, mut response: String, mut lookup: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PurposeRoutedAdmissionProvider {
    pub initialized: bool,
}

impl PurposeRoutedAdmissionProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn admit(&self, mut evidence_digest: String, mut scope_digest: String, mut purpose_id: String, mut source_revision: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["OperationalEvidenceAdmissionProvider", "OperationalProofReader", "PurposeRoutedAdmissionProvider"];
