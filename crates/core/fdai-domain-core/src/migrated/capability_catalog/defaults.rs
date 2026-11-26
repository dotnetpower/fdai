pub const TOOLS: &str = "https://learn.microsoft.com/azure/sre-agent/tools";
pub const DIAGNOSE: &str = "https://learn.microsoft.com/azure/sre-agent/diagnose-azure-observability";
pub const MEMORY: &str = "https://learn.microsoft.com/azure/sre-agent/memory";
pub const INCIDENTS: &str = "https://learn.microsoft.com/azure/sre-agent/incident-platforms";
pub const PLANS: &str = "https://learn.microsoft.com/azure/sre-agent/incident-response-plans";
pub const SCHEDULES: &str = "https://learn.microsoft.com/azure/sre-agent/scheduled-tasks";
pub const WORKFLOWS: &str = "https://learn.microsoft.com/azure/sre-agent/workflow-automation";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::too_many_arguments)]
pub fn parity(mut capability_id: String, mut name: String, mut category: String, mut summary: String, mut source: String, mut evidence: Vec<String>, mut side_effect: String, mut status: String, mut role: String) -> String {
    if capability_id.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn default_capability_catalog() -> String {
    core::hint::black_box(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["default_capability_catalog"];
