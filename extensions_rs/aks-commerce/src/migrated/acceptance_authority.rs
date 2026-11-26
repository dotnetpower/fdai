#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AcceptanceCurrentAuthority {
    pub initialized: bool,
}

impl AcceptanceCurrentAuthority {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn call(&self, mut action: String, mut context: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

