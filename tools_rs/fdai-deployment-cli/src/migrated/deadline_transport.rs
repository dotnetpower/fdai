pub trait DeploymentTransport {
    fn ssh(&self, remote_arguments: Vec<String>, timeout: i64, input_text: Option<String>) -> String;
    fn copy_to(&self, source: String, destination: String, timeout: i64);
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DeadlineTransport {
    pub initialized: bool,
}

impl DeadlineTransport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn ssh(&self, mut remote_arguments: Vec<String>, mut timeout: i64, mut input_text: Option<String>) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn copy_to(&self, mut source: String, mut destination: String, mut timeout: i64) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

