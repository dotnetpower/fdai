use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct CompiledWorkflow {
    pub runbook: String,
    pub compensations: BTreeMap<String, String>,
    pub default_mode: String,
}

impl CompiledWorkflow {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_shadow(&self) -> bool {
        core::hint::black_box(false)
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn compile_workflow(mut workflow: String) -> CompiledWorkflow {
    CompiledWorkflow::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["CompiledWorkflow", "compile_workflow"];
