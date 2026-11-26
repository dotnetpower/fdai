#[derive(Clone, Debug, Default, PartialEq)]
pub struct LocalizedWorkflowAppText {
    pub en: String,
    pub ko: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowAppManifest {
    pub schema_version: String,
    pub id: String,
    pub workflow_ref: String,
    pub view_ref: String,
    pub lifecycle: String,
    pub audience: String,
    pub label: Box<LocalizedWorkflowAppText>,
    pub description: Box<LocalizedWorkflowAppText>,
    pub exposure: String,
    pub group: String,
    pub order: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowAppCatalogIssue {
    pub origin: String,
    pub message: String,
}

impl WorkflowAppManifest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn route(&self) -> String {
        format!("/workflow-apps/{}", self.id.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_hub_visible(&self) -> bool {
        ((self.lifecycle.clone()) == (String::from("published"))) && ((self.exposure.clone()) == (String::from("hub")))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("id"), self.id.clone()), (String::from("workflow_ref"), self.workflow_ref.clone()), (String::from("view_ref"), self.view_ref.clone()), (String::from("lifecycle"), self.lifecycle.clone()), (String::from("audience"), self.audience.clone()), (String::from("label"), String::new()), (String::from("description"), String::new()), (String::from("route"), String::new()), (String::from("group"), self.group.clone()), (String::from("order"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct WorkflowAppCatalogError {
    pub message: String,
}

impl WorkflowAppCatalogError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for WorkflowAppCatalogError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for WorkflowAppCatalogError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_workflow_app_catalog(mut root: String, mut workflow_names: std::collections::BTreeSet<String>, mut view_workflows: std::collections::BTreeMap<String, String>, mut schema_path: Option<String>) -> Result<Vec<WorkflowAppManifest>, &'static str> {
    let mut manifests: Vec<WorkflowAppManifest> = Vec::<WorkflowAppManifest>::new();
    let mut issues: Vec<WorkflowAppCatalogIssue> = Vec::<WorkflowAppCatalogIssue>::new();
    let mut seen_ids: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let mut seen_workflows: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    if !(issues.clone()).is_empty() {
        return Err("issues");
    }
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn manifest(mut raw: std::collections::BTreeMap<String, String>) -> Result<WorkflowAppManifest, &'static str> {
    Ok(WorkflowAppManifest { label: Box::new(LocalizedWorkflowAppText::default()), description: Box::new(LocalizedWorkflowAppText::default()), ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["LocalizedWorkflowAppText", "WorkflowAppCatalogError", "WorkflowAppCatalogIssue", "WorkflowAppManifest", "load_workflow_app_catalog"];
