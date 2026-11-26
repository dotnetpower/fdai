#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CommandArgumentKind {
    #[default]
    StringContract,
    Integer,
    Boolean,
}

impl CommandArgumentKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::StringContract => "string",
            Self::Integer => "integer",
            Self::Boolean => "boolean",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CommandArgumentSource {
    #[default]
    Request,
    Trusted,
}

impl CommandArgumentSource {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Request => "request",
            Self::Trusted => "trusted",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CommandArgumentSpec {
    pub name: String,
    pub kind: CommandArgumentKind,
    pub source: CommandArgumentSource,
    pub flag: Option<String>,
    pub required: bool,
    pub pattern: Option<String>,
    pub minimum: Option<i64>,
    pub maximum: Option<i64>,
    pub choices: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CommandSpec {
    pub command_id: String,
    pub version: i64,
    pub executable_ref: String,
    pub fixed_argv: Vec<String>,
    pub arguments: Vec<CommandArgumentSpec>,
    pub execution_class: String,
    pub network_profile: String,
    pub output_format: String,
    pub timeout_seconds: i64,
    pub max_output_bytes: i64,
    pub credential_profile: Option<String>,
    pub workspace_required: bool,
}

pub const IDENTIFIER: &str = "^[a-z][a-z0-9_.-]{0,127}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CommandCatalog {
    pub initialized: bool,
}

impl CommandCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn resolve(&self, mut command_id: String, mut arguments: std::collections::BTreeMap<String, String>, mut trusted_values: std::collections::BTreeMap<String, String>, mut idempotency_key: String, mut dry_run: bool, mut workspace_ref: Option<String>) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn validated_value(mut spec: CommandArgumentSpec, mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["CommandArgumentKind", "CommandArgumentSource", "CommandArgumentSpec", "CommandCatalog", "CommandSpec"];
