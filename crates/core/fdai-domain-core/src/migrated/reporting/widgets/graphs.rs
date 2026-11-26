#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TimeseriesBuilder {
    pub initialized: bool,
}

impl TimeseriesBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("series"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct QueryValueBuilder {
    pub initialized: bool,
}

impl QueryValueBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        let mut payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("value"), String::new())]);
        payload.clone()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ChangeBuilder {
    pub initialized: bool,
}

impl ChangeBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("current"), String::new()), (String::from("previous"), String::new()), (String::from("delta_absolute"), String::new()), (String::from("delta_ratio"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DistributionBuilder {
    pub initialized: bool,
}

impl DistributionBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        let mut buckets: Vec<String> = Vec::<String>::new();
        std::collections::BTreeMap::from([(String::from("buckets"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HeatmapBuilder {
    pub initialized: bool,
}

impl HeatmapBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("series"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BarChartBuilder {
    pub initialized: bool,
}

impl BarChartBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("bars"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PieChartBuilder {
    pub initialized: bool,
}

impl PieChartBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        let mut slices: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
        let mut magnitude_total: f64 = 0.0;
        let mut signed_total: f64 = 0.0;
        std::collections::BTreeMap::from([(String::from("slices"), String::new()), (String::from("total"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ScatterPlotBuilder {
    pub initialized: bool,
}

impl ScatterPlotBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        let mut points: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
        std::collections::BTreeMap::from([(String::from("points"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SparklineBuilder {
    pub initialized: bool,
}

impl SparklineBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        let mut series: Vec<String> = Vec::<String>::new();
        std::collections::BTreeMap::from([(String::from("series"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GaugeBuilder {
    pub initialized: bool,
}

impl GaugeBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        let value: Option<String> = as_number(String::new());
        let low: Option<String> = as_number(String::new());
        let high: Option<String> = as_number(String::new());
        let mut ratio: Option<f64> = None;
        std::collections::BTreeMap::from([(String::from("value"), (value.clone()).unwrap_or_default()), (String::from("min"), String::new()), (String::from("max"), String::new()), (String::from("ratio"), String::new()), (String::from("unit"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProgressBarBuilder {
    pub initialized: bool,
}

impl ProgressBarBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        let current_raw: Option<String> = as_number(String::new());
        let target_raw: Option<String> = as_number(String::new());
        std::collections::BTreeMap::from([(String::from("current"), String::new()), (String::from("target"), String::new()), (String::from("ratio"), String::new()), (String::from("unit"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn extract_pair(mut data: String) -> (Option<String>, Option<String>) {
    (None, None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn as_number(mut value: String) -> Option<String> {
    if false {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn sortable(mut value: String) -> (i64, String) {
    if (true) && (!(false)) {
        return (0_i64, value.clone());
    }
    (1_i64, value.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["BarChartBuilder", "ChangeBuilder", "DistributionBuilder", "GaugeBuilder", "HeatmapBuilder", "PieChartBuilder", "ProgressBarBuilder", "QueryValueBuilder", "ScatterPlotBuilder", "SparklineBuilder", "TimeseriesBuilder"];
