#[derive(Clone, Debug, Default, PartialEq)]
pub struct EventBusReadInvestigationCompletionSink {
    pub audit: String,
    pub topic: String,
}

impl EventBusReadInvestigationCompletionSink {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn bind(&mut self, mut bus: String) {
        if bus.is_empty() {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn unbind(&mut self) {
        core::sync::atomic::compiler_fence(core::sync::atomic::Ordering::SeqCst);
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn publish(&self, mut attempt: String) -> Result<(), &'static str> {
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["EventBusReadInvestigationCompletionSink"];
