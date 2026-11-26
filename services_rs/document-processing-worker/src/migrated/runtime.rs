use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct DocumentWorkerRuntime {
    pub environ: BTreeMap<String, String>,
    pub worker_factory: String,
}

impl DocumentWorkerRuntime {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn run(&self) -> i64 {
        0_i64
    }
}

