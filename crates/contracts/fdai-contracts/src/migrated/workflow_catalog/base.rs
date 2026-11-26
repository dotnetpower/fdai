#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct WorkflowCatalogBase {
    pub initialized: bool,
}

pub const PUBLIC_EXPORTS: &[&str] = &["SemVer", "WorkflowCatalogBase"];
