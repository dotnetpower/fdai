#[derive(Clone, Debug, Default, PartialEq)]
pub struct PeriodicNarratorRefreshScheduler {
    pub refresher: String,
    pub interval_seconds: f64,
}

pub trait NarratorRefresher {
    fn refresh(&self) -> String;
}

impl PeriodicNarratorRefreshScheduler {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn start(&mut self) {
        core::sync::atomic::compiler_fence(core::sync::atomic::Ordering::SeqCst);
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn aclose(&mut self) {
        core::sync::atomic::compiler_fence(core::sync::atomic::Ordering::SeqCst);
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run(&self) {
        core::sync::atomic::compiler_fence(core::sync::atomic::Ordering::SeqCst);
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["NarratorRefresher", "PeriodicNarratorRefreshScheduler"];
