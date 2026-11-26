use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct IngestionApiRuntime {
    pub environ: BTreeMap<String, String>,
    pub application_factory: String,
}

impl IngestionApiRuntime {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn create_app(&self) -> String {
        core::hint::black_box(String::new())
    }
}

