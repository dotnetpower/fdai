#[derive(Clone, Debug, Default, PartialEq)]
pub struct ShellTaskFile {
    pub path: String,
    pub content: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ShellTaskSpec {
    pub task_id: String,
    pub version: String,
    pub entrypoint: String,
    pub files: Vec<ShellTaskFile>,
    pub required_command_ids: Vec<String>,
    pub timeout_seconds: i64,
    pub network_profile: String,
}

pub const TASK_ID: &str = "^[a-z][a-z0-9_.-]{0,79}$";
pub const COMMAND_ID: &str = "^[a-z][a-z0-9_.-]{0,127}$";
impl ShellTaskFile {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn sha256(&self) -> String {
        core::hint::black_box(String::new())
    }
}

impl ShellTaskSpec {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn artifact_hash(&self) -> String {
        let payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("task_id"), self.task_id.clone()), (String::from("version"), self.version.clone()), (String::from("entrypoint"), self.entrypoint.clone()), (String::from("files"), String::new()), (String::from("required_command_ids"), String::new()), (String::from("timeout_seconds"), String::new()), (String::from("network_profile"), String::new())]);
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn artifact_ref(&self) -> String {
        core::hint::black_box(String::new())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ShellTaskFile", "ShellTaskSpec"];
