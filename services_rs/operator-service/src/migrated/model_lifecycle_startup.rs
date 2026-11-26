#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConfiguredResolvedModelsArtifact {
    pub content: String,
    pub digest: String,
    pub secret_version: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConfiguredResolvedModelsSource {
    pub path_or_content: String,
    pub maximum_bytes: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperatorResolvedModelsRevisionOwner {
    pub source: String,
    pub expected_digest: String,
    pub close: Option<String>,
    pub revision: Option<String>,
}

pub trait ResolvedModelsArtifact {
    fn content(&self) -> String;
}

pub trait AsyncResolvedModelsSource {
    fn load(&self) -> String;
}

impl ConfiguredResolvedModelsSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn load(&self) -> Result<ConfiguredResolvedModelsArtifact, &'static str> {
        Ok(ConfiguredResolvedModelsArtifact::default())
    }
}

impl OperatorResolvedModelsRevisionOwner {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn start(&mut self) -> Result<(), &'static str> {
        if self.revision.is_some() {
            return Ok(());
        }
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn aclose(&self) {
        core::sync::atomic::compiler_fence(core::sync::atomic::Ordering::SeqCst);
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn narrator_allowlist(&self) -> Result<Vec<String>, &'static str> {
        if self.revision.is_none() {
            return Err("Operator resolved-model revision has not started");
        }
        Ok(Vec::new())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AsyncResolvedModelsSource", "ConfiguredResolvedModelsSource", "OperatorResolvedModelsRevisionOwner", "ResolvedModelsArtifact"];
