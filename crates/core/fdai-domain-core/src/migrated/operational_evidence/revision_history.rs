#[derive(Clone, Debug, Default, PartialEq)]
pub struct RegistryPins {
    pub trust_pin: String,
    pub grant_pin: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RegistryRevision {
    pub trust: String,
    pub grants: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LineageBinding {
    pub purpose_id: String,
    pub verifier_id: String,
    pub verifier_version: String,
    pub trust_anchor_id: String,
    pub matched_grants: Vec<String>,
}

impl RegistryPins {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        core::hint::black_box(String::new())
    }
}

impl RegistryRevision {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn pins(&self) -> RegistryPins {
        RegistryPins::default()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RegistryHistory {
    pub initialized: bool,
}

impl RegistryHistory {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn current(&self) -> RegistryRevision {
        if !self.initialized {
            return Default::default();
        }
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn step_classes(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn admitting_pins(&self) -> std::collections::BTreeSet<String> {
        std::collections::BTreeSet::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn lineage_intact(&self, mut pins_digest: String, mut binding: LineageBinding, mut at: String) -> bool {
        self.initialized
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["LineageBinding", "RegistryHistory", "RegistryPins", "RegistryRevision"];
