pub trait DocumentArtifactReader {
    fn read_artifact(&self, document_id: String, version_id: String) -> String;
}

pub trait PreviewProtectionAuthorizer {
    fn authorize(&self, actor_id: String, actor_groups: std::collections::BTreeSet<String>, version: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MetadataPreviewProtectionAuthorizer {
    pub initialized: bool,
}

impl MetadataPreviewProtectionAuthorizer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn authorize(&self, mut actor_id: String, mut actor_groups: std::collections::BTreeSet<String>, mut version: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GovernedDocumentPreview {
    pub initialized: bool,
}

impl GovernedDocumentPreview {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn preview(&self, mut actor_id: String, mut actor_groups: std::collections::BTreeSet<String>, mut document_id: String, mut version_id: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

