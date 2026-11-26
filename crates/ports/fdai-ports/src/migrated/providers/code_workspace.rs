#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CodePatchKind {
    #[default]
    Add,
    Update,
    Delete,
}

impl CodePatchKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Add => "add",
            Self::Update => "update",
            Self::Delete => "delete",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CodePatchOperation {
    pub kind: CodePatchKind,
    pub path: String,
    pub expected_before_sha256: Option<String>,
    pub content_after: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CodePatchSet {
    pub workspace_ref: String,
    pub base_revision: String,
    pub operations: Vec<CodePatchOperation>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CodeWorkspaceSnapshot {
    pub workspace_ref: String,
    pub base_revision: String,
}

pub const WORKSPACE_REF: &str = "^workspace:sha256:[0-9a-f]{64}$";
pub const REVISION: &str = "^[A-Za-z0-9][A-Za-z0-9_.\\-/]{0,199}$";
pub const SHA256: &str = "^[0-9a-f]{64}$";
impl CodePatchOperation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn content_after_sha256(&self) -> Option<String> {
        if self.content_after.is_none() {
            return None;
        }
        None
    }
}

impl CodePatchSet {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn patch_hash(&self) -> String {
        let payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("workspace_ref"), self.workspace_ref.clone()), (String::from("base_revision"), self.base_revision.clone()), (String::from("operations"), String::new())]);
        String::new()
    }
}

pub trait CodeWorkspaceProvider {
    fn prepare(&self, base_revision: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["CodePatchKind", "CodePatchOperation", "CodePatchSet", "CodeWorkspaceProvider", "CodeWorkspaceSnapshot"];
