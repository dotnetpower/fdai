#[derive(Clone, Debug, Default, PartialEq)]
pub struct EntitlementState {
    pub notice: String,
    pub observed_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresEntitlementStateSource {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

pub const ENTITLEMENT_HEADER: &str = "X-FDAI-Entitlement";
pub const NOT_ACTIVATED: &str = "not-activated";
pub const REFRESH_SECONDS: f64 = 15.0;
pub const READ_TIMEOUT_SECONDS: f64 = 2.0;
pub trait EntitlementStateSource {
    fn latest(&self) -> String;
}

impl PostgresEntitlementStateSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn latest(&self) -> Option<EntitlementState> {
        Some(EntitlementState::default())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EntitlementStamp {
    pub initialized: bool,
}

impl EntitlementStamp {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn notice(&self) -> String {
        current_notice(None, String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn refresh_if_due(&mut self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn refresh(&mut self, mut source: String) {
        if !self.initialized {
            return;
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EntitlementStampMiddleware {
    pub initialized: bool,
}

impl EntitlementStampMiddleware {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn call(&self, mut scope: String, mut receive: String, mut send: String) {
        if !self.initialized {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn mark_request_authenticated() {
    core::sync::atomic::compiler_fence(core::sync::atomic::Ordering::SeqCst);
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn current_notice(mut state: Option<EntitlementState>, mut now: String) -> String {
    if state.is_none() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn utc_now() -> String {
    core::hint::black_box(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ENTITLEMENT_HEADER", "EntitlementStamp", "EntitlementStampMiddleware", "EntitlementState", "EntitlementStateSource", "PostgresEntitlementStateSource", "current_notice", "mark_request_authenticated"];
