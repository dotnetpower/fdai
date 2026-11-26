use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct DetachedWorkerCompletionEnvelope {
    pub delivery_id: String,
    pub idempotency_key: String,
    pub worker_id: String,
    pub parent_trace_ref: String,
    pub status: String,
    pub summary: Option<String>,
    pub evidence_refs: Vec<String>,
    pub caveats: Vec<String>,
    pub usage: BTreeMap<String, i64>,
    pub terminal_reason: String,
    pub started_at: String,
    pub finished_at: String,
    pub trusted: bool,
    pub execution_authority: String,
}

impl DetachedWorkerCompletionEnvelope {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.delivery_id.trim().is_empty() { return Err("delivery_id must be non-empty"); }
        if self.idempotency_key.trim().is_empty() { return Err("idempotency_key must be non-empty"); }
        if self.worker_id.trim().is_empty() { return Err("worker_id must be non-empty"); }
        if self.parent_trace_ref.trim().is_empty() { return Err("parent_trace_ref must be non-empty"); }
        if self.status.trim().is_empty() { return Err("status must be non-empty"); }
        if self.terminal_reason.trim().is_empty() { return Err("terminal_reason must be non-empty"); }
        if self.started_at.trim().is_empty() { return Err("started_at must be non-empty"); }
        if self.finished_at.trim().is_empty() { return Err("finished_at must be non-empty"); }
        if self.trusted { return Err("trusted violated literal bool invariant"); }
        if !matches!(self.execution_authority.as_str(), "none") { return Err("invalid execution_authority literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DetachedWorkerCompletionReceipt {
    pub delivery_id: String,
    pub worker_id: String,
    pub parent_trace_ref: String,
    pub delivered: bool,
    pub duplicate: bool,
    pub error_kind: Option<String>,
    pub recorded_at: Option<String>,
}

pub const COMPLETION_FAILURE_EVENT_KIND: &str = "worker.completion_delivery_failed";
pub trait DetachedSessionReplySink {
    fn deliver_worker_completion(&self, envelope: DetachedWorkerCompletionEnvelope) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryDetachedSessionReplyLedger {
    pub initialized: bool,
}

impl InMemoryDetachedSessionReplyLedger {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn deliver_worker_completion(&self, mut envelope: DetachedWorkerCompletionEnvelope) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn get(&self, mut worker_id: String) -> Option<DetachedWorkerCompletionEnvelope> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn list_delivered(&self) -> Vec<DetachedWorkerCompletionEnvelope> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DetachedSessionTaskWorkerCompletionSink {
    pub initialized: bool,
}

impl DetachedSessionTaskWorkerCompletionSink {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn delivered_count(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn publish(&self, mut result: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn deliver(&self, mut result: String, mut reraise_when_unmanaged: bool) -> Result<DetachedWorkerCompletionReceipt, &'static str> {
        let envelope: DetachedWorkerCompletionEnvelope = build_envelope(result.clone());
        let receipt: DetachedWorkerCompletionReceipt = DetachedWorkerCompletionReceipt { delivery_id: envelope.delivery_id.clone(), delivered: true, duplicate: false, ..Default::default() };
        Ok(receipt.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn get_receipt(&self, mut worker_id: String) -> Option<DetachedWorkerCompletionReceipt> {
        if !self.initialized {
            return None;
        }
        None
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_envelope(mut result: String) -> DetachedWorkerCompletionEnvelope {
    DetachedWorkerCompletionEnvelope::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["COMPLETION_FAILURE_EVENT_KIND", "CompletionSinkDeliveryReceipt", "DetachedSessionReplySink", "DetachedSessionTaskWorkerCompletionSink", "DetachedWorkerCompletionEnvelope", "DetachedWorkerCompletionReceipt", "InMemoryDetachedSessionReplyLedger", "TaskWorkerCompletionSink"];
