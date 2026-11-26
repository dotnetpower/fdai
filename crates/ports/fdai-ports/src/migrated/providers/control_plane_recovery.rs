#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RegionalRecoveryAction {
    #[default]
    ProvisionRecoveryRegion,
    FencePrimary,
    ReplayEvents,
    ShiftTraffic,
    Failback,
}

impl RegionalRecoveryAction {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ProvisionRecoveryRegion => "provision_recovery_region",
            Self::FencePrimary => "fence_primary",
            Self::ReplayEvents => "replay_events",
            Self::ShiftTraffic => "shift_traffic",
            Self::Failback => "failback",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecoveryApprovalEvidence {
    pub approval_ref: String,
    pub actor_ref: String,
    pub plan_id: String,
    pub plan_revision: i64,
    pub target_state: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RegionalRecoveryShadowRequest {
    pub action: RegionalRecoveryAction,
    pub plan_id: String,
    pub plan_revision: i64,
    pub recovery_epoch: i64,
    pub primary_region: String,
    pub recovery_region: String,
    pub scope: Vec<String>,
    pub replay_start: String,
    pub replay_end: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RegionalRecoveryShadowReceipt {
    pub action: RegionalRecoveryAction,
    pub succeeded: bool,
    pub observed_epoch: i64,
    pub primary_writer_active: bool,
    pub recovery_writer_active: bool,
    pub evidence_refs: Vec<String>,
}

pub trait RecoveryApprovalVerifier {
    fn verify(&self, evidence: RecoveryApprovalEvidence) -> bool;
}

pub trait RegionalRecoveryActionProvider {
    fn evaluate_shadow(&self, request: RegionalRecoveryShadowRequest) -> RegionalRecoveryShadowReceipt;
}

pub const PUBLIC_EXPORTS: &[&str] = &["RecoveryApprovalEvidence", "RecoveryApprovalVerifier", "RegionalRecoveryAction", "RegionalRecoveryActionProvider", "RegionalRecoveryShadowReceipt", "RegionalRecoveryShadowRequest"];
