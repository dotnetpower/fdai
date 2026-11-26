#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SecurityFindingProviderError {
    pub message: String,
}

impl SecurityFindingProviderError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for SecurityFindingProviderError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SecurityFindingProviderError {}

pub trait SecurityFindingProvider {
    fn collect(&self, scope: String, since: Option<String>, until: Option<String>) -> Vec<String>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EmptySecurityFindingProvider {
    pub initialized: bool,
}

impl EmptySecurityFindingProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn collect(&self, mut scope: String, mut since: Option<String>, mut until: Option<String>) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CompositeSecurityFindingProvider {
    pub initialized: bool,
}

impl CompositeSecurityFindingProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn collect(&self, mut scope: String, mut since: Option<String>, mut until: Option<String>) -> Vec<String> {
        let mut merged: Vec<String> = Vec::<String>::new();
        merged.clone()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["CompositeSecurityFindingProvider", "EmptySecurityFindingProvider", "SecurityFindingProvider", "SecurityFindingProviderError"];
