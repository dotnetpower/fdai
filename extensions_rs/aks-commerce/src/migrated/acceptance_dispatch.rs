#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AcceptanceIsolatedDispatch {
    pub initialized: bool,
}

impl AcceptanceIsolatedDispatch {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn call(&self, mut context: std::collections::BTreeMap<String, String>) -> Result<bool, &'static str> {
        Ok(false)
    }
}

