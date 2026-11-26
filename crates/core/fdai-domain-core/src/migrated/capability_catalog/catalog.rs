#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CapabilityCategory {
    #[default]
    Detection,
    Investigation,
    Remediation,
    Chaos,
    Knowledge,
    Incident,
    Scheduling,
    ResponsePlan,
    Cost,
    Reporting,
}

impl CapabilityCategory {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Detection => "detection",
            Self::Investigation => "investigation",
            Self::Remediation => "remediation",
            Self::Chaos => "chaos",
            Self::Knowledge => "knowledge",
            Self::Incident => "incident",
            Self::Scheduling => "scheduling",
            Self::ResponsePlan => "response_plan",
            Self::Cost => "cost",
            Self::Reporting => "reporting",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SideEffectClass {
    #[default]
    Read,
    Simulate,
    Approve,
    Execute,
    Breakglass,
}

impl SideEffectClass {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Read => "read",
            Self::Simulate => "simulate",
            Self::Approve => "approve",
            Self::Execute => "execute",
            Self::Breakglass => "breakglass",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CapabilityParity {
    #[default]
    Native,
    SaferAlternative,
    ExternalBinding,
}

impl CapabilityParity {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Native => "native",
            Self::SaferAlternative => "safer-alternative",
            Self::ExternalBinding => "external-binding",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Capability {
    pub capability_id: String,
    pub name: String,
    pub category: CapabilityCategory,
    pub summary: String,
    pub side_effect_class: SideEffectClass,
    pub default_mode: String,
    pub required_role: String,
    pub slide_ref: Option<String>,
    pub enabled: bool,
    pub tags: Vec<String>,
    pub parity: CapabilityParity,
    pub official_source: Option<String>,
    pub evidence_refs: Vec<String>,
}

impl Capability {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.capability_id.trim().is_empty() { return Err("capability_id must be non-empty"); }
        if self.name.trim().is_empty() { return Err("name must be non-empty"); }
        if self.summary.trim().is_empty() { return Err("summary must be non-empty"); }
        if self.default_mode.trim().is_empty() { return Err("default_mode must be non-empty"); }
        if self.required_role.trim().is_empty() { return Err("required_role must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DuplicateCapabilityError {
    pub message: String,
}

impl DuplicateCapabilityError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DuplicateCapabilityError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DuplicateCapabilityError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CapabilityCatalog {
    pub initialized: bool,
}

impl CapabilityCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn register(&self, mut capability: Capability) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn get(&self, mut capability_id: String) -> Option<Capability> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn list(&self, mut category: Option<CapabilityCategory>, mut enabled_only: bool) -> Vec<Capability> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    #[allow(clippy::type_complexity)]
    pub fn as_console_view(&self) -> Vec<std::collections::BTreeMap<String, String>> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["Capability", "CapabilityCatalog", "CapabilityCategory", "CapabilityParity", "DuplicateCapabilityError", "SideEffectClass"];
