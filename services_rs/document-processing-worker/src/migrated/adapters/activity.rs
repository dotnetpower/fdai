#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresDocumentActivitySink {
    pub initialized: bool,
}

impl PostgresDocumentActivitySink {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn outbox_dlq_count(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn outbox_dlq_failure_count(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn drain(&mut self, mut limit: i64) -> Result<i64, &'static str> {
        if ((limit) < (1_i64)) || ((limit) > (1000_i64)) {
            return Err("outbox drain limit MUST be in 1 1000");
        }
        let mut published: i64 = 0_i64;
        Ok(published)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn claim(&self, mut limit: i64) -> Vec<std::collections::BTreeMap<String, String>> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn mark_published(&self, mut event_id: String) {
        if !self.initialized {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn payload(mut value: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Err("document worker outbox payload is not a JSON object")
}

