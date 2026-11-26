use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RowUnit {
    #[default]
    Ratio,
    Count,
}

impl RowUnit {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Ratio => "ratio",
            Self::Count => "count",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct KpiRow {
    pub metric: String,
    pub value: f64,
    pub unit: RowUnit,
    pub dimensions: BTreeMap<String, String>,
}

pub const METRIC_SAMPLE_COUNT: &str = "prompt.recognition.sample_count";
pub const METRIC_ADHERENCE_PASS_RATE: &str = "prompt.recognition.adherence.pass_rate";
pub const METRIC_ADHERENCE_VIOLATION_COUNT: &str = "prompt.recognition.adherence.violation_count";
pub const METRIC_CANARY_ECHO_RATE: &str = "prompt.recognition.canary_echo_rate";
pub const METRIC_CITATION_F1_MEAN: &str = "prompt.recognition.citation_f1.mean";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn emit_kpi_rows(mut report: String, mut dimensions: Option<std::collections::BTreeMap<String, String>>) -> Vec<KpiRow> {
    let mut rows: Vec<KpiRow> = vec![KpiRow { metric: String::from(METRIC_SAMPLE_COUNT), ..Default::default() }];
    rows.clone()
}

pub const PUBLIC_EXPORTS: &[&str] = &["KpiRow", "METRIC_ADHERENCE_PASS_RATE", "METRIC_ADHERENCE_VIOLATION_COUNT", "METRIC_CANARY_ECHO_RATE", "METRIC_CITATION_F1_MEAN", "METRIC_SAMPLE_COUNT", "RowUnit", "emit_kpi_rows"];
