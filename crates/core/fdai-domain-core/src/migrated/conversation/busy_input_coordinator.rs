#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActiveConversationTurn {
    pub session_id: String,
    pub turn_id: String,
    pub principal_id: String,
    pub cancel_event: String,
    pub steer_event: String,
}

pub trait BusyInputMetrics {
    fn increment(&self, name: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BusyInputCoordinator {
    pub initialized: bool,
}

impl BusyInputCoordinator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn begin_turn(&self, mut session_id: String, mut turn_id: String, mut principal_id: String, mut mode: Option<String>) -> Result<ActiveConversationTurn, &'static str> {
        let active: ActiveConversationTurn = ActiveConversationTurn { session_id: session_id.clone(), turn_id: turn_id.clone(), principal_id: principal_id.clone(), ..Default::default() };
        Ok(active.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn submit(&self, mut incoming: String, mut now: Option<String>) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn safe_boundary(&self, mut session_id: String, mut principal_id: String, mut at: Option<String>) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn finish_turn(&self, mut session_id: String, mut turn_id: String, mut principal_id: String) {
        let mut steer_fallbacks: i64 = 0_i64;
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn pending(&self, mut session_id: String, mut principal_id: String) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn status(&self, mut session_id: String, mut principal_id: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn set_mode(&self, mut session_id: String, mut principal_id: String, mut mode: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn cancel_current(&self, mut session_id: String, mut principal_id: String) -> bool {
        if !self.initialized {
            return true;
        }
        true
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn expire_pending(&self, mut now: String, mut limit: i64) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn active(&self, mut session_id: String) -> Option<ActiveConversationTurn> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn increment(&self, mut name: String) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ActiveConversationTurn", "BusyInputCoordinator", "BusyInputMetrics"];
