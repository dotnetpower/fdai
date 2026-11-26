use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleActivationProposalClaim {
    pub key: String,
    pub claim_id: String,
    pub record: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleActivationNoticeDrainer {
    pub store: String,
    pub publisher: String,
}

pub trait RuleActivationOutboxStore {
    fn claim(&self) -> String;
}

pub trait RuleActivationNoticePublisher {
    fn publish(&self, topic: String, key: String, payload: std::collections::BTreeMap<String, String>) -> String;
}

impl RuleActivationNoticeDrainer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run_once(&self) -> bool {
        core::hint::black_box(false)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RuleActivationNoticeBridge {
    pub initialized: bool,
}

impl RuleActivationNoticeBridge {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn workers_ready(&self) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn start(&mut self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn aclose(&mut self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run(&mut self) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["RuleActivationNoticeBridge", "RuleActivationNoticeDrainer", "RuleActivationNoticePublisher", "RuleActivationOutboxStore", "RuleActivationProposalClaim"];
