#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerticalDescriptor {
    pub vertical_id: String,
    pub display_name: String,
    pub category: String,
    pub rule_source_ids: Vec<String>,
    pub enabled: bool,
    pub default_mode: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct VerticalRegistrationError {
    pub message: String,
}

impl VerticalRegistrationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for VerticalRegistrationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for VerticalRegistrationError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct VerticalRegistry {
    pub initialized: bool,
}

impl VerticalRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn register(&self, mut descriptor: VerticalDescriptor) -> Result<(), &'static str> {
        let vid: String = descriptor.vertical_id.clone();
        if (vid.clone()).is_empty() {
            return Err("vertical_id MUST be non-empty");
        }
        if (descriptor.enabled) && ((descriptor.rule_source_ids.clone()).is_empty()) {
            return Err("enabled vertical vid MUST name at least one rule source  a domain with n");
        }
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn register_all(&self, mut descriptors: Vec<VerticalDescriptor>) {
        for descriptor in descriptors.clone() {
            let _ = self.register(descriptor.clone()).unwrap_or_else(|_| ());
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn get(&self, mut vertical_id: String) -> VerticalDescriptor {
        if !self.initialized {
            return Default::default();
        }
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn has(&self, mut vertical_id: String) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn all(&self) -> Vec<VerticalDescriptor> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn enabled(&self) -> Vec<VerticalDescriptor> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["VerticalDescriptor", "VerticalRegistrationError", "VerticalRegistry"];
