#[derive(Clone, Debug, Default, PartialEq)]
pub struct KubeResult {
    pub exit_code: i64,
    pub output: String,
}

pub const READ_ONLY_VERBS: &[&str] = &["get", "logs"];
pub trait KubeTransport {
    #[allow(clippy::type_complexity)]
    fn run(&self, args: Vec<String>, manifest: Option<Vec<u8>>, timeout: i64) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct KubectlTransport {
    pub initialized: bool,
}

impl KubectlTransport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn run(&self, mut args: Vec<String>, mut manifest: Option<Vec<u8>>, mut timeout: i64) -> Result<KubeResult, &'static str> {
        Ok(KubeResult::default())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AksRunCommandTransport {
    pub initialized: bool,
}

impl AksRunCommandTransport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn run(&self, mut args: Vec<String>, mut manifest: Option<Vec<u8>>, mut timeout: i64) -> Result<KubeResult, &'static str> {
        Err("unreachable")
    }
}

