pub trait ExemptionLifecycleNotifier {
    fn notify_expiry_digest(&self, digest: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LoggingExemptionLifecycleNotifier {
    pub initialized: bool,
}

impl LoggingExemptionLifecycleNotifier {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn notify_expiry_digest(&self, mut digest: String) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ExemptionLifecycleNotifier", "LoggingExemptionLifecycleNotifier"];
