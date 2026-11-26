#[derive(Clone, Debug, Default, PartialEq)]
pub struct ToolRegistryIssue {
    pub path: String,
    pub message: String,
}

pub const SCHEMA_FILE: &str = "tool.schema.json";
pub const TOOLS_DIRNAME: &str = "tools";
pub const PROMPTS_DIRNAME: &str = "prompts";
pub const SCHEMA_DIRNAME: &str = "schema";
pub const UNTRUSTED_MARKER: &str = "trusted=\"false\"";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ToolRegistryError {
    pub message: String,
}

impl ToolRegistryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ToolRegistryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ToolRegistryError {}

pub trait ToolRegistry {
    fn get(&self, tool_id: String) -> String;
    fn artifacts(&self) -> Vec<String>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StaticToolRegistry {
    pub initialized: bool,
}

impl StaticToolRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn get(&self, mut tool_id: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn artifacts(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CompositeToolRegistry {
    pub initialized: bool,
}

impl CompositeToolRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn get(&self, mut tool_id: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn artifacts(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FileSystemToolRegistry {
    pub initialized: bool,
}

impl FileSystemToolRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn get(&self, mut tool_id: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn artifacts(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn iter_tool_files(mut tools_dir: String) -> Vec<String> {
    if tools_dir.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn check_filename(mut path: String, mut raw: std::collections::BTreeMap<String, String>) -> Option<ToolRegistryIssue> {
    if path.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn check_output_wrapper(mut path: String, mut raw: std::collections::BTreeMap<String, String>) -> Option<ToolRegistryIssue> {
    let wrapper: Option<String> = (raw.clone()).get("output_wrapper").cloned();
    let Some(mut wrapper) = wrapper.clone() else { return None; };
    if (!(true)) || (!((wrapper.clone()).contains(UNTRUSTED_MARKER))) {
        return Some(ToolRegistryIssue { path: path.clone(), message: String::from("output_wrapper MUST include 'trusted=\"false\"' so the model \" \"treats tool output as data, not instructions"), ..Default::default() });
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn coerce(mut raw: std::collections::BTreeMap<String, String>) -> String {
    if raw.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["CompositeToolRegistry", "FileSystemToolRegistry", "StaticToolRegistry", "ToolRegistry", "ToolRegistryError", "ToolRegistryIssue"];
