#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WorkflowTriggerEventSemantics {
    #[default]
    Request,
    Command,
    Observation,
}

impl WorkflowTriggerEventSemantics {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Request => "request",
            Self::Command => "command",
            Self::Observation => "observation",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowTriggerEventEntry {
    pub id: String,
    pub semantics: WorkflowTriggerEventSemantics,
    pub description: String,
    pub owner: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowTriggerEventRegistry {
    pub schema_version: String,
    pub events: Vec<WorkflowTriggerEventEntry>,
}

impl WorkflowTriggerEventRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn model_post_init(&self, mut context: String) -> Result<(), &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn ids(&self) -> std::collections::BTreeSet<String> {
        std::collections::BTreeSet::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["WorkflowTriggerEventEntry", "WorkflowTriggerEventRegistry", "WorkflowTriggerEventSemantics"];
