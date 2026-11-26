#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct OnboardingProbeError {
    pub message: String,
}

impl OnboardingProbeError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for OnboardingProbeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for OnboardingProbeError {}

pub trait ResourceProbe {
    fn observed_resources(&self) -> Vec<String>;
    fn observed_role_assignments(&self) -> Vec<String>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EmptyResourceProbe {
    pub initialized: bool,
}

impl EmptyResourceProbe {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observed_resources(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observed_role_assignments(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct OnboardingVerifier {
    pub initialized: bool,
}

impl OnboardingVerifier {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn verify(&self, mut spec: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn default_onboarding_spec() -> String {
    core::hint::black_box(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["EmptyResourceProbe", "OnboardingProbeError", "OnboardingVerifier", "ResourceProbe", "default_onboarding_spec"];
