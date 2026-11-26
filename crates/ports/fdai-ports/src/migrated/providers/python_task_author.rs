#[derive(Clone, Debug, Default, PartialEq)]
pub struct PythonTaskAuthorRequest {
    pub intent: String,
    pub task_id_hint: String,
    pub target_capabilities: Vec<String>,
    pub allowed_modules: Vec<String>,
}

pub trait PythonTaskAuthor {
    fn author(&self, request: PythonTaskAuthorRequest) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["PythonTaskAuthor", "PythonTaskAuthorRequest"];
