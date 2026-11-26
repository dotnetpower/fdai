pub const KILL_SWITCH_STATE_KEY: &str = "system:kill-switch";
pub trait KillSwitch {
    fn is_engaged(&self) -> bool;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryKillSwitch {
    pub initialized: bool,
}

impl InMemoryKillSwitch {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_engaged(&self) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn engage(&mut self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn disengage(&mut self) {
        if !self.initialized {
            return;
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StateStoreKillSwitch {
    pub initialized: bool,
}

impl StateStoreKillSwitch {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_engaged(&self) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn refresh(&mut self) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["KILL_SWITCH_STATE_KEY", "InMemoryKillSwitch", "KillSwitch", "StateStoreKillSwitch"];
