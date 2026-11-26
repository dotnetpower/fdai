pub const MAX_ROWS: i64 = 200;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProcessStepsBuilder {
    pub initialized: bool,
}

impl ProcessStepsBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        let mut steps: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
        let mut completed: i64 = 0_i64;
        std::collections::BTreeMap::from([(String::from("steps"), String::new()), (String::from("completed"), String::new()), (String::from("total"), String::new()), (String::from("progress_ratio"), String::new()), (String::from("truncated"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ComparisonBuilder {
    pub initialized: bool,
}

impl ComparisonBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        let mut rows: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
        let mut changed_count: i64 = 0_i64;
        std::collections::BTreeMap::from([(String::from("rows"), String::new()), (String::from("changed_count"), String::new()), (String::from("total"), String::new()), (String::from("truncated"), String::new())])
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ComparisonBuilder", "ProcessStepsBuilder"];
