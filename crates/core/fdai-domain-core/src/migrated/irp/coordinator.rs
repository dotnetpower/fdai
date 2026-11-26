#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ApprovalDecision {
    #[default]
    Approved,
    Rejected,
    Timeout,
}

impl ApprovalDecision {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Approved => "approved",
            Self::Rejected => "rejected",
            Self::Timeout => "timeout",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum IrpOutcome {
    #[default]
    NoFinding,
    Approved,
    PendingApproval,
    Rejected,
    Timeout,
}

impl IrpOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::NoFinding => "no_finding",
            Self::Approved => "approved",
            Self::PendingApproval => "pending_approval",
            Self::Rejected => "rejected",
            Self::Timeout => "timeout",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alert {
    pub alert_id: String,
    pub signal: String,
    pub resources: Vec<String>,
    pub fired_at: String,
}

impl Alert {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.alert_id.trim().is_empty() { return Err("alert_id must be non-empty"); }
        if self.signal.trim().is_empty() { return Err("signal must be non-empty"); }
        if self.fired_at.trim().is_empty() { return Err("fired_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MitigationProposal {
    pub proposal_id: String,
    pub alert_id: String,
    pub remediation_ref: String,
    pub detail: String,
    pub priority: String,
    pub approver_role: String,
    pub citations: Vec<String>,
    pub requested_at: String,
    pub target_resource_ref: String,
}

impl MitigationProposal {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.proposal_id.trim().is_empty() { return Err("proposal_id must be non-empty"); }
        if self.alert_id.trim().is_empty() { return Err("alert_id must be non-empty"); }
        if self.remediation_ref.trim().is_empty() { return Err("remediation_ref must be non-empty"); }
        if self.detail.trim().is_empty() { return Err("detail must be non-empty"); }
        if self.priority.trim().is_empty() { return Err("priority must be non-empty"); }
        if self.approver_role.trim().is_empty() { return Err("approver_role must be non-empty"); }
        if self.requested_at.trim().is_empty() { return Err("requested_at must be non-empty"); }
        if self.target_resource_ref.trim().is_empty() { return Err("target_resource_ref must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IrpResult {
    pub alert_id: String,
    pub outcome: IrpOutcome,
    pub report: String,
    #[allow(clippy::type_complexity)]
    pub proposal: Option<Box<MitigationProposal>>,
    pub decision: Option<ApprovalDecision>,
    pub notified_channels: Vec<String>,
    pub started_at: String,
    pub ended_at: String,
    pub investigation_within_budget: bool,
}

pub const DEFAULT_INVESTIGATION_BUDGET: f64 = 60.0;
pub const DEFAULT_APPROVER_ROLE: &str = "approver";
pub const HANG_GRACE: f64 = 2.0;
pub trait ApprovalGate {
    fn request(&self, proposal: MitigationProposal) -> String;
}

pub trait IrpNotifier {
    fn notify(&self, channels: Vec<String>, subject: String, body: String) -> String;
}

pub trait ProposalRouter {
    fn route(&self, proposal: MitigationProposal) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DenyByDefaultApprovalGate {
    pub initialized: bool,
}

impl DenyByDefaultApprovalGate {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn request(&self, mut proposal: MitigationProposal) -> ApprovalDecision {
        if !self.initialized {
            return Default::default();
        }
        Default::default()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NullNotifier {
    pub initialized: bool,
}

impl NullNotifier {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn notify(&self, mut channels: Vec<String>, mut subject: String, mut body: String) {
        if !self.initialized {
            return;
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct IrpCoordinator {
    pub initialized: bool,
}

impl IrpCoordinator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn respond(&self, mut alert: Alert, mut plan: Option<String>) -> IrpResult {
        let proposal: MitigationProposal = MitigationProposal { alert_id: alert.alert_id.clone(), ..Default::default() };
        self.result(alert.clone(), Default::default(), String::new(), Some(proposal.clone()), None, Vec::new(), String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn top_actionable(mut report: String) -> Option<String> {
        if report.is_empty() {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn request_approval(&self, mut proposal: MitigationProposal, mut alert_id: String) -> ApprovalDecision {
        if !self.initialized {
            return Default::default();
        }
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn route_proposal(&self, mut proposal: MitigationProposal, mut alert_id: String) -> bool {
        if !self.initialized {
            return true;
        }
        true
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn timed_out_report(&self, mut request: String, mut started: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn errored_report(&self, mut request: String, mut started: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn notify(&self, mut channels: Vec<String>, mut subject: String, mut body: String) {
        if (channels.clone()).is_empty() {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    #[allow(clippy::too_many_arguments)]
    pub fn result(&self, mut alert: Alert, mut outcome: IrpOutcome, mut report: String, mut proposal: Option<MitigationProposal>, mut decision: Option<ApprovalDecision>, mut channels: Vec<String>, mut started: String) -> IrpResult {
        IrpResult { alert_id: alert.alert_id.clone(), outcome: outcome.clone(), report: report.clone(), proposal: (proposal.clone()).map(Box::new), decision: decision.clone(), notified_channels: channels.clone(), started_at: started.clone(), ..Default::default() }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["Alert", "ApprovalDecision", "ApprovalGate", "DenyByDefaultApprovalGate", "IrpCoordinator", "IrpNotifier", "IrpOutcome", "IrpResult", "MitigationProposal", "NullNotifier", "ProposalRouter"];
