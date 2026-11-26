use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WorkflowOrigin {
    #[default]
    Upstream,
    Tenant,
    User,
}

impl WorkflowOrigin {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Upstream => "upstream",
            Self::Tenant => "tenant",
            Self::User => "user",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WorkflowVisibility {
    #[default]
    Global,
    Team,
    Private,
}

impl WorkflowVisibility {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Global => "global",
            Self::Team => "team",
            Self::Private => "private",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WorkflowLifecycle {
    #[default]
    Draft,
    Validated,
    Shadow,
    Published,
    Suspended,
    Retired,
}

impl WorkflowLifecycle {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Draft => "draft",
            Self::Validated => "validated",
            Self::Shadow => "shadow",
            Self::Published => "published",
            Self::Suspended => "suspended",
            Self::Retired => "retired",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WorkflowBindingTrigger {
    #[default]
    DeckOpen,
    Schedule,
    Signal,
}

impl WorkflowBindingTrigger {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::DeckOpen => "deck_open",
            Self::Schedule => "schedule",
            Self::Signal => "signal",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowDefinitionRecord {
    pub definition_id: String,
    pub workflow_name: String,
    pub workflow_version: String,
    pub schema_version: String,
    pub definition_hash: String,
    pub action_catalog_digest: String,
    pub resolved_action_versions: BTreeMap<String, String>,
    pub workflow_document: BTreeMap<String, String>,
    pub origin: WorkflowOrigin,
    pub visibility: WorkflowVisibility,
    pub lifecycle: WorkflowLifecycle,
    pub created_at: String,
    pub owner_ref: Option<String>,
    pub derived_from: Option<String>,
    pub source_ref: Option<String>,
}

impl WorkflowDefinitionRecord {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.definition_id.trim().is_empty() { return Err("definition_id must be non-empty"); }
        if self.workflow_name.trim().is_empty() { return Err("workflow_name must be non-empty"); }
        if self.workflow_version.trim().is_empty() { return Err("workflow_version must be non-empty"); }
        if self.schema_version.trim().is_empty() { return Err("schema_version must be non-empty"); }
        if self.definition_hash.trim().is_empty() { return Err("definition_hash must be non-empty"); }
        if self.action_catalog_digest.trim().is_empty() { return Err("action_catalog_digest must be non-empty"); }
        if self.created_at.trim().is_empty() { return Err("created_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowBindingRecord {
    pub binding_id: String,
    pub principal_id: String,
    pub definition_id: String,
    pub trigger: WorkflowBindingTrigger,
    pub enabled: bool,
    pub created_at: String,
    pub updated_at: String,
    pub revision: i64,
    pub scope_ref: Option<String>,
    pub cron_expression: Option<String>,
    pub timezone: Option<String>,
    pub signal_type: Option<String>,
    pub parameters: BTreeMap<String, String>,
}

impl WorkflowBindingRecord {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.binding_id.trim().is_empty() { return Err("binding_id must be non-empty"); }
        if self.principal_id.trim().is_empty() { return Err("principal_id must be non-empty"); }
        if self.definition_id.trim().is_empty() { return Err("definition_id must be non-empty"); }
        if self.created_at.trim().is_empty() { return Err("created_at must be non-empty"); }
        if self.updated_at.trim().is_empty() { return Err("updated_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct WorkflowDefinitionConflictError {
    pub message: String,
}

impl WorkflowDefinitionConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for WorkflowDefinitionConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for WorkflowDefinitionConflictError {}

pub trait WorkflowDefinitionStore {
    fn put(&self, record: WorkflowDefinitionRecord) -> String;
}

pub trait WorkflowBindingStore {
    fn create(&self, record: WorkflowBindingRecord) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["WorkflowBindingRecord", "WorkflowBindingStore", "WorkflowBindingTrigger", "WorkflowDefinitionConflictError", "WorkflowDefinitionRecord", "WorkflowDefinitionStore", "WorkflowLifecycle", "WorkflowOrigin", "WorkflowVisibility"];
