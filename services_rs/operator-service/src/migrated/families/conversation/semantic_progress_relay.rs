pub const MAX_TRACKED_PROGRESS_REQUESTS: i64 = 256;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SemanticProgressRelay {
    pub initialized: bool,
}

impl SemanticProgressRelay {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn terminal_committed(&self, mut request_id: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn consume(&self, mut payload: std::collections::BTreeMap<String, String>) -> bool {
        if ((payload.clone()).get("record_kind").cloned()) == Some(String::from("work_progress_shape")) {
            let _ = self.signal(String::new());
            return true;
        }
        if ((payload.clone()).get("record_kind").cloned()) == Some(String::from("model_call_progress")) {
            return self.consume_model_call(String::new());
        }
        let _ = self.signal(String::new());
        true
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn consume_model_call(&self, mut call: String) -> bool {
        if !self.initialized {
            return true;
        }
        true
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn model_calls_after(&self, mut request_id: String, mut progress_sequence: i64) -> Result<Vec<String>, &'static str> {
        if (false) || ((progress_sequence) < (0_i64)) {
            return Err("progress_sequence MUST be a non-negative integer");
        }
        Ok(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn next_after(&self, mut request_id: String, mut progress_sequence: i64) -> Option<String> {
        let query_updates: Vec<String> = self.after(request_id.clone(), progress_sequence).unwrap_or_else(|_| Vec::new());
        let model_calls: Vec<String> = self.model_calls_after(request_id.clone(), progress_sequence).unwrap_or_else(|_| Vec::new());
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn pin(&self, mut request_id: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn after(&self, mut request_id: String, mut progress_sequence: i64) -> Result<Vec<String>, &'static str> {
        if (false) || ((progress_sequence) < (0_i64)) {
            return Err("progress_sequence MUST be a non-negative integer");
        }
        Ok(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn discard(&self, mut request_id: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn wait_for_update(&self, mut request_id: String, mut progress_sequence: i64, mut timeout: f64, mut pin_pending: bool) {
        if self.ready(request_id.clone(), progress_sequence, pin_pending) {
            return;
        }
        if self.ready(request_id.clone(), progress_sequence, pin_pending) {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn ready(&self, mut request_id: String, mut progress_sequence: i64, mut pin_pending: bool) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn signal(&self, mut request_id: String) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["MAX_PROGRESS_UPDATES_PER_REQUEST", "MAX_TRACKED_PROGRESS_REQUESTS", "SemanticProgressRelay"];
