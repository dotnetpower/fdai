use std::collections::BTreeMap;
pub const MAX_DECLARATION_BYTES: i64 = 65536;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DeclaredWindow {
    pub start: String,
    pub duration: String,
    pub timezone: String,
    pub allows_downtime: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DeclaredSettings {
    pub channel: String,
    pub version_range: String,
    pub region: String,
    pub allowed_regions: Vec<String>,
    pub windows: Vec<DeclaredWindow>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DeclaredConfiguration {
    pub schema_: BTreeMap<String, String>,
    pub environment: BTreeMap<String, String>,
    #[allow(clippy::type_complexity)]
    pub entity_overrides: Vec<BTreeMap<String, String>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InstallationDeclaration {
    pub schema_version: String,
    pub installation_id: String,
    pub settings: Box<DeclaredSettings>,
    pub configuration: Box<DeclaredConfiguration>,
}

impl InstallationDeclaration {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "fdai.lifecycle-installation-declaration.v1") { return Err("invalid schema_version literal"); }
        Ok(())
    }
}

pub const DECLARATION_SCHEMA: &str = "fdai.lifecycle-installation-declaration.v1";
pub const IDENTIFIER: &str = "^[a-z][a-z0-9-]{0,62}$";
pub const CHANNEL: &str = "^[A-Za-z][A-Za-z0-9_-]{0,63}$";
pub const RANGE: &str = "^[\\x21-\\x7e]+(?: [\\x21-\\x7e]+)*$";
pub const WALL_CLOCK: &str = "^[0-2][0-9]:[0-5][0-9]:[0-5][0-9]$";
pub const DURATION: &str = "^P(?:[0-9]+D)?(?:T(?:[0-9]+H)?(?:[0-9]+M)?(?:[0-9]+S)?)?$";
pub const ZONE: &str = "^[A-Za-z][A-Za-z0-9_+/-]{0,63}$";
impl InstallationDeclaration {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn enrollment_template(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("installation_id"), self.installation_id.clone()), (String::from("settings"), String::new()), (String::from("configuration"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DeclarationError {
    pub message: String,
}

impl DeclarationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DeclarationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DeclarationError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_declaration(mut path: String) -> Result<InstallationDeclaration, &'static str> {
    if path.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

