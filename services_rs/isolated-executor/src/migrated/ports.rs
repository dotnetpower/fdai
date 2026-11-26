use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct PendingExecutorReceipt {
    pub receipt_id: String,
    pub partition_key: String,
    pub payload: BTreeMap<String, String>,
    pub command_id: Option<String>,
    pub command_offset: Option<i64>,
}

pub trait ExecutorReceiptOutbox {
    fn read_committed_receipt(&self, command_id: String) -> String;
}

pub trait ExecutorStateStore {
    fn append_audit_entry(&self, entry: std::collections::BTreeMap<String, String>) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["ExecutorReceiptOutbox", "ExecutorStateStore", "PendingExecutorReceipt"];
