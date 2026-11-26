#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SafeguardExecutionOrigin {
    #[default]
    Core,
    Workflow,
}

impl SafeguardExecutionOrigin {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Core => "core",
            Self::Workflow => "workflow",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SafeguardExecutionVenue {
    #[default]
    Core,
    IsolatedExecutor,
}

impl SafeguardExecutionVenue {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Core => "core",
            Self::IsolatedExecutor => "isolated_executor",
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resolve_execution_origin(mut action: String) -> SafeguardExecutionOrigin {
    if action.is_empty() {
        return Default::default();
    }
    Default::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["SafeguardExecutionOrigin", "SafeguardExecutionVenue", "resolve_execution_origin"];
