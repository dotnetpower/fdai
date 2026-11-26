#[derive(Clone, Debug, Default, PartialEq)]
pub struct PromptRegistryIssue {
    pub path: String,
    pub message: String,
}

pub const SCHEMA_FILE: &str = "prompt.schema.json";
pub const PROMPTS_DIRNAME: &str = "prompts";
pub const SCHEMA_DIRNAME: &str = "schema";
pub const PEER_SUBSYSTEM_DIRNAMES: &[&str] = &["history", "profiles", "tools", "scenarios"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PromptRegistryError {
    pub message: String,
}

impl PromptRegistryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for PromptRegistryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PromptRegistryError {}

pub trait LegacyPromptRegistry {
    fn get_base(&self, capability_id: String) -> String;
    fn get_packs(&self, capability_id: String) -> Vec<String>;
    fn artifacts(&self) -> Vec<String>;
}

pub trait PromptRegistry {
    fn get_base(&self, capability_id: String) -> String;
    fn get_packs(&self, capability_id: String) -> Vec<String>;
    fn artifacts(&self) -> Vec<String>;
    fn resolve(&self, capability_id: String, profile_id: Option<String>) -> String;
    fn profiles(&self) -> Vec<String>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FileSystemPromptRegistry {
    pub initialized: bool,
}

impl FileSystemPromptRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn get_base(&self, mut capability_id: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn get_packs(&self, mut capability_id: String) -> Vec<String> {
        let mut by_id: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn artifacts(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn resolve(&self, mut capability_id: String, mut profile_id: Option<String>) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn profiles(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn resolve_prompt_selection(mut registry: String, mut capability_id: String, mut profile_id: Option<String>) -> Result<String, &'static str> {
    if let Some(mut profile_id) = profile_id.clone() {
        return Err("explicit profile selection requires a profile-aware registry");
    }
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn iter_prompt_files(mut prompts_dir: String) -> Vec<String> {
    if prompts_dir.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn check_filename(mut path: String, mut raw: std::collections::BTreeMap<String, String>) -> Option<PromptRegistryIssue> {
    if path.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn coerce(mut raw: std::collections::BTreeMap<String, String>, mut provenance_default: String) -> String {
    let token_budget_raw: Option<String> = (raw.clone()).get("token_budget").cloned();
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn as_iter(mut value: String) -> Result<Vec<String>, &'static str> {
    Err("expected list got typevalue.__name__")
}

pub const PUBLIC_EXPORTS: &[&str] = &["FileSystemPromptRegistry", "LegacyPromptRegistry", "PromptRegistry", "PromptRegistryError", "PromptRegistryIssue", "resolve_prompt_selection"];
