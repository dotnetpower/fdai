#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SignalDispatchMode {
    #[default]
    Baseline,
    Exact,
}

impl SignalDispatchMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Baseline => "baseline",
            Self::Exact => "exact",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SignalTypeEntry {
    pub id: String,
    pub dispatch_mode: SignalDispatchMode,
    pub event_type_patterns: Vec<String>,
    pub description: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SignalTypeRegistry {
    pub schema_version: String,
    pub types: Vec<SignalTypeEntry>,
}

impl SignalTypeRegistry {
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
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn resolve_declared(&self, mut event_type: Option<String>) -> std::collections::BTreeSet<String> {
        let value: String = (((event_type.clone()).unwrap_or_else(|| String::from(""))).trim().to_string()).to_lowercase();
        std::collections::BTreeSet::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn resolve(&self, mut event_type: Option<String>) -> std::collections::BTreeSet<String> {
        let exact: std::collections::BTreeSet<String> = self.resolve_declared(event_type.clone());
        std::collections::BTreeSet::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["SignalDispatchMode", "SignalTypeEntry", "SignalTypeRegistry"];
