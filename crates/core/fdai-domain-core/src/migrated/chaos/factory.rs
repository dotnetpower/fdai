pub const NON_EXECUTABLE_MARKERS: &[&str] = &["needs-injector", "cross-csp-reference"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct UnavailableInjectorError {
    pub message: String,
}

impl UnavailableInjectorError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for UnavailableInjectorError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for UnavailableInjectorError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct UnavailableProbeError {
    pub message: String,
}

impl UnavailableProbeError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for UnavailableProbeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for UnavailableProbeError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ScenarioFactory {
    pub initialized: bool,
}

impl ScenarioFactory {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn register_injector(&self, mut injector_ref: String, mut builder: String) -> Result<(), &'static str> {
        if (injector_ref.trim().to_string()).is_empty() {
            return Err("injector_ref MUST be non-empty");
        }
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn register_probe(&self, mut expected_signal: String, mut builder: String) -> Result<(), &'static str> {
        if (expected_signal.trim().to_string()).is_empty() {
            return Err("expected_signal MUST be non-empty");
        }
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_executable(&self, mut entry: String) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn executable_entries(&self, mut entries: Vec<String>) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn build(&self, mut entry: String, mut context: Option<std::collections::BTreeMap<String, String>>) -> Result<(String, String), &'static str> {
        let builder: Option<String> = self.resolve_injector(entry.clone());
        let Some(mut builder) = builder.clone() else { return Err("entry.id: no injector builder registered for entry.specinjectorr"); };
        Ok((String::new(), String::new()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn registered_injectors(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn registered_probes(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn resolve_injector(&self, mut entry: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InjectorBuilder", "NON_EXECUTABLE_MARKERS", "ProbeBuilder", "ScenarioFactory", "UnavailableInjectorError", "UnavailableProbeError"];
