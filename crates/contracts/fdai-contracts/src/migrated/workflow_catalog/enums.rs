#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Mode {
    #[default]
    Shadow,
    Enforce,
}

impl Mode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Shadow => "shadow",
            Self::Enforce => "enforce",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CeilingRole {
    #[default]
    Reader,
    Contributor,
    Approver,
    Owner,
}

impl CeilingRole {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Reader => "reader",
            Self::Contributor => "contributor",
            Self::Approver => "approver",
            Self::Owner => "owner",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WorkflowTriggerKind {
    #[default]
    Signal,
    Schedule,
}

impl WorkflowTriggerKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Signal => "signal",
            Self::Schedule => "schedule",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WorkflowTriggerSignalReferenceKind {
    #[default]
    SignalType,
    WorkflowTriggerEvent,
}

impl WorkflowTriggerSignalReferenceKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::SignalType => "signal_type",
            Self::WorkflowTriggerEvent => "workflow_trigger_event",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WorkflowStepKind {
    #[default]
    Action,
    Wait,
    Approval,
    Decision,
    Parallel,
    Gate,
    Evidence,
}

impl WorkflowStepKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Action => "action",
            Self::Wait => "wait",
            Self::Approval => "approval",
            Self::Decision => "decision",
            Self::Parallel => "parallel",
            Self::Gate => "gate",
            Self::Evidence => "evidence",
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["CEILING_ROLE_RANK", "CeilingRole", "Mode", "WorkflowStepKind", "WorkflowTriggerKind", "WorkflowTriggerSignalReferenceKind"];
