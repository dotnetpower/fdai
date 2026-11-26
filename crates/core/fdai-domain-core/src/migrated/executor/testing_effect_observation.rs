#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryIndependentEffectObservationStore {
    pub initialized: bool,
}

impl InMemoryIndependentEffectObservationStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn append(&self, mut receipt: String) -> Result<String, &'static str> {
        Ok(receipt.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read_lineage(&self, mut evidence_identity_digest: String) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryIndependentEffectObservationStore"];
