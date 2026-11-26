pub const MAX_PROCESSES: i64 = 32;
pub const MAX_SAMPLES: i64 = 10000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VmProcessCpuObservation {
    pub resource_id: String,
    pub process_name: String,
    pub average_cpu_percent: f64,
    pub maximum_cpu_percent: f64,
    pub sample_count: i64,
    pub first_observed_at: String,
    pub last_observed_at: String,
    pub evidence_ref: String,
}

impl VmProcessCpuObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.resource_id.trim().is_empty() { return Err("resource_id must be non-empty"); }
        if self.process_name.trim().is_empty() { return Err("process_name must be non-empty"); }
        if self.first_observed_at.trim().is_empty() { return Err("first_observed_at must be non-empty"); }
        if self.last_observed_at.trim().is_empty() { return Err("last_observed_at must be non-empty"); }
        if self.evidence_ref.trim().is_empty() { return Err("evidence_ref must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VmProcessCpuCollection {
    pub resource_id: String,
    pub start: String,
    pub end: String,
    pub observed_at: String,
    pub observations: Vec<VmProcessCpuObservation>,
    pub complete: bool,
    pub truncated: bool,
    pub limitation: Option<String>,
    pub attempt_ref: String,
}

impl VmProcessCpuCollection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.resource_id.trim().is_empty() { return Err("resource_id must be non-empty"); }
        if self.start.trim().is_empty() { return Err("start must be non-empty"); }
        if self.end.trim().is_empty() { return Err("end must be non-empty"); }
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        if self.attempt_ref.trim().is_empty() { return Err("attempt_ref must be non-empty"); }
        Ok(())
    }
}

pub const VM_PROCESS_CPU_FUNCTION_NAME: &str = "query.vm_process_cpu_evidence";
pub trait VmProcessCpuReader {
    fn read_process_cpu(&self, resource_id: String, start: String, end: String, limit: i64) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn vm_process_cpu_function_type() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn vm_process_cpu_function(mut ontology_release: String, mut reader: String) -> Result<String, &'static str> {
    if ontology_release.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn table(mut rows: Vec<String>, mut complete: bool, mut reason: Option<String>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["VM_PROCESS_CPU_FUNCTION_NAME", "VmProcessCpuCollection", "VmProcessCpuObservation", "VmProcessCpuReader", "vm_process_cpu_function", "vm_process_cpu_function_type"];
