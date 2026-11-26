use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct RoutedDirectApiExecutor {
    pub routes: BTreeMap<String, String>,
    pub identity_routes: BTreeMap<String, String>,
    pub fallback: Option<String>,
}

impl RoutedDirectApiExecutor {
    pub fn validate(&self) -> Result<(), &'static str> {
        Err("runtime_binding_required")
    }
}

impl RoutedDirectApiExecutor {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn execute(&self, mut request: String) -> Result<String, &'static str> {
        if request.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["RoutedDirectApiExecutor"];
