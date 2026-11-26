#[derive(Clone, Debug, Default, PartialEq)]
pub struct MemberRead {
    pub target: String,
    pub definition: String,
    pub window: Option<String>,
    pub pending_reason: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MetricSelection {
    pub comparator: Option<String>,
    pub threshold: Option<i64>,
    pub descending: Option<bool>,
    pub limit: Option<i64>,
    pub list_unknown: bool,
}

pub const METRIC_BUDGET_EXHAUSTED: &str = "metric_budget_exhausted";
pub const METRIC_PROVIDER_UNAVAILABLE: &str = "metric_provider_unavailable";
pub const COMPARATORS: &[&str] = &["gt", "ge", "lt", "le"];
pub const DIRECTIONS: &[&str] = &["ascending", "descending"];
impl MetricSelection {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn selective(&self) -> bool {
        (self.comparator.is_some()) || (self.descending.is_some())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_arguments(mut arguments: std::collections::BTreeMap<String, String>, mut definitions: Vec<String>) -> Result<MetricSelection, &'static str> {
        if (((definitions.clone()).len() as i64)) != (1_i64) {
            return Err("a metric comparison or order reads exactly one concept");
        }
        let mut selection: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("list_unknown"), String::new())]);
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn matches(&self, mut value: f64) -> bool {
        if (self.comparator.is_none()) || (self.threshold.is_none()) {
            return true;
        }
        false
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub async fn read_members(mut targets: Vec<String>, mut definitions: Vec<String>, mut provider: String, mut start: String, mut end: String, mut max_reads: i64, mut batch_size: i64, mut concurrency: i64) -> Result<(Vec<MemberRead>, Option<String>), &'static str> {
    if ((max_reads) < (1_i64)) || (((batch_size) < (1_i64)) || ((concurrency) < (1_i64))) {
        return Err("metric read budget batch size and concurrency MUST be positive");
    }
    let mut reads: Vec<MemberRead> = Vec::<MemberRead>::new();
    let mut stop: Option<String> = None;
    Ok((reads.clone(), stop.clone()))
}

pub const PUBLIC_EXPORTS: &[&str] = &["METRIC_BUDGET_EXHAUSTED", "METRIC_PROVIDER_UNAVAILABLE", "MemberRead", "MetricSelection", "read_members"];
