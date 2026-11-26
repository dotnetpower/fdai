pub const TERMINAL_RECEIPT_RETAIN: i64 = 5000;

pub const TERMINAL_STATUSES: &[&str] = &["invalidated", "published"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MimirCatalogReviewJournal {
    pub initialized: bool,
}

impl MimirCatalogReviewJournal {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn durable(&self) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn bind(&mut self, mut store: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn retain(&self, mut candidate: std::collections::BTreeMap<String, String>, mut package: String) -> Result<Option<String>, &'static str> {
        let value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("kind"), String::new()), (String::from("revision"), String::new()), (String::from("status"), String::from("pending")), (String::from("idempotency_key"), String::new()), (String::from("candidate_digest"), String::new()), (String::from("package_digest"), String::new()), (String::from("candidate"), String::new())]);
        Err("Mimir catalog review durable status is invalid")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn pending_candidates(&self) -> Result<(Vec<std::collections::BTreeMap<String, String>>, i64), &'static str> {
        let mut pending: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
        Ok((Vec::new(), 0_i64))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn publication_receipt(&self, mut candidate: std::collections::BTreeMap<String, String>, mut candidate_digest: String) -> Result<Option<String>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn pending_identity(&self, mut candidate: std::collections::BTreeMap<String, String>, mut candidate_digest: Option<String>) -> Result<Option<(String, String)>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn mark_published(&self, mut candidate: std::collections::BTreeMap<String, String>, mut package: String, mut receipt: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn invalidate(&self, mut candidate: std::collections::BTreeMap<String, String>, mut reason: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn mark_terminal(&self, mut candidate: std::collections::BTreeMap<String, String>, mut candidate_digest: String, mut package_digest: String, mut status: String, mut reason: String, mut review_ref: Option<String>) -> Result<(), &'static str> {
        let terminal: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("kind"), String::new()), (String::from("revision"), String::new()), (String::from("status"), status.clone()), (String::from("idempotency_key"), String::new()), (String::from("candidate_digest"), candidate_digest.clone()), (String::from("package_digest"), package_digest.clone()), (String::from("reason"), reason.clone())]);
        Ok(())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["MimirCatalogReviewJournal"];
