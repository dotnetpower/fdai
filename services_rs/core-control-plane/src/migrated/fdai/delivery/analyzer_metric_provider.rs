#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AnalyzerMetricProvider {
    pub initialized: bool,
}

impl AnalyzerMetricProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn query(&self, mut query: String) -> Result<Vec<String>, &'static str> {
        Err("ailure from None")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn identity(mut value: String) -> String {
    value.clone()
}

pub const PUBLIC_EXPORTS: &[&str] = &["AnalyzerMetricProvider"];
