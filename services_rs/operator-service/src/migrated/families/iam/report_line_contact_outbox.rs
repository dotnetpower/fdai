#[derive(Clone, Debug, Default, PartialEq)]
pub struct DurableReportLineContactPublisher {
    pub durable: String,
    pub publisher: String,
    pub topic: String,
    pub ledger: Option<String>,
}

impl DurableReportLineContactPublisher {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.durable.trim().is_empty() { return Err("durable must be non-empty"); }
        if self.publisher.trim().is_empty() { return Err("publisher must be non-empty"); }
        if self.topic.trim().is_empty() { return Err("topic must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportLineContactOutboxDrainer {
    pub store: String,
    pub publisher: String,
    pub topic: String,
    pub worker_id: String,
    pub lease_seconds: i64,
}

pub const REPORT_LINE_CONTACT_ENQUEUE_OPERATION: &str = "hil.report-line-contact.enqueue";
pub trait ReportLineContactPublisher {
    fn publish(&self, topic: String, key: String, payload: std::collections::BTreeMap<String, String>) -> String;
}

pub trait ReportLineContactDeliveryLedger {
    fn mark_report_line_contact_published(&self, idempotency_key: String) -> String;
}

impl DurableReportLineContactPublisher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get_report_line_contact_context(&self, mut approval_id: String) -> Option<String> {
        if approval_id.is_empty() {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list_report_line_contact_contexts(&self, mut requester_ref: String, mut limit: i64) -> Vec<String> {
        if requester_ref.is_empty() {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn enqueue_report_line_contact(&self, mut command: String) {
        if command.is_empty() {
            return;
        }
    }
}

pub trait ReportLineContactClaim {
    fn key(&self) -> String;
}

pub trait ReportLineContactOutboxStore {
    fn claim_report_line_contact_proposal(&self, worker_id: String, lease_seconds: i64) -> String;
}

impl ReportLineContactOutboxDrainer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run_once(&self) -> bool {
        core::hint::black_box(false)
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["REPORT_LINE_CONTACT_ENQUEUE_OPERATION", "DurableReportLineContactPublisher", "ReportLineContactDeliveryLedger", "ReportLineContactOutboxDrainer", "ReportLineContactOutboxStore", "ReportLineContactPublisher"];
