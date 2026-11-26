use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OutboxStatus {
    #[default]
    New,
    InProgress,
    Done,
}

impl OutboxStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::New => "new",
            Self::InProgress => "in_progress",
            Self::Done => "done",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OutboxClaim {
    pub status: OutboxStatus,
    #[allow(clippy::type_complexity)]
    pub result: Option<BTreeMap<String, String>>,
}

pub trait OutboxStore {
    fn claim(&self, key: String) -> OutboxClaim;
    fn complete(&self, key: String, result: std::collections::BTreeMap<String, String>);
}

pub const PUBLIC_EXPORTS: &[&str] = &["OutboxStore", "OutboxStatus", "OutboxClaim"];
