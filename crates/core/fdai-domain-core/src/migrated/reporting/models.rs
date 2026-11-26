use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TimeGrain {
    #[default]
    Minute,
    FiveMinute,
    FifteenMinute,
    Hour,
    Day,
    Week,
}

impl TimeGrain {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Minute => "1m",
            Self::FiveMinute => "5m",
            Self::FifteenMinute => "15m",
            Self::Hour => "1h",
            Self::Day => "1d",
            Self::Week => "1w",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TimeRange {
    pub since: Option<String>,
    pub until: Option<String>,
    pub relative_duration: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Variable {
    pub name: String,
    pub default: Option<String>,
    pub values: Vec<String>,
    pub description: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct QuerySpec {
    pub datasource: String,
    pub parameters: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WidgetSpec {
    pub id: String,
    pub r#type: String,
    pub title: String,
    #[allow(clippy::type_complexity)]
    pub query: Option<Box<QuerySpec>>,
    pub options: BTreeMap<String, String>,
    pub children: Vec<WidgetSpec>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportSpec {
    pub id: String,
    pub version: String,
    pub name: String,
    pub description: String,
    pub time_range: Box<TimeRange>,
    pub variables: Vec<Variable>,
    pub widgets: Vec<WidgetSpec>,
    pub tags: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Series {
    pub label: String,
    pub points: Vec<String>,
    pub labels: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DataSet {
    pub columns: Vec<String>,
    #[allow(clippy::type_complexity)]
    pub rows: Vec<BTreeMap<String, String>>,
    pub series: Vec<Series>,
    pub scalar: Option<f64>,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RenderedWidget {
    pub id: String,
    pub r#type: String,
    pub title: String,
    pub data: BTreeMap<String, String>,
    pub options: BTreeMap<String, String>,
    pub error: Option<String>,
    pub children: Vec<RenderedWidget>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DataSourceProvenance {
    pub datasource: String,
    pub source: String,
    pub availability: String,
    pub synthetic: Option<bool>,
    pub as_of: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportProvenance {
    pub availability: String,
    pub synthetic: Option<bool>,
    pub sources: Vec<DataSourceProvenance>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RenderedReport {
    pub id: String,
    pub version: String,
    pub name: String,
    pub description: String,
    pub generated_at: String,
    pub time_range: String,
    pub variables: BTreeMap<String, String>,
    pub widgets: Vec<RenderedWidget>,
    pub tags: Vec<String>,
    pub provenance: Box<ReportProvenance>,
}

impl TimeRange {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn resolve(&self, mut now: String) -> Result<(String, String), &'static str> {
        if (self.since.is_some()) && (self.until.is_some()) {
            return Ok(((self.since.clone()).unwrap_or_default(), (self.until.clone()).unwrap_or_default()));
        }
        let until: String = (self.until.clone()).unwrap_or_else(|| now.clone());
        if self.since.is_some() {
            return Ok(((self.since.clone()).unwrap_or_default(), until.clone()));
        }
        if self.relative_duration.is_none() {
            return Err("TimeRange needs at least one of since  relative_duration");
        }
        Ok((String::new(), String::new()))
    }
}

impl DataSourceProvenance {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("datasource"), self.datasource.clone()), (String::from("source"), self.source.clone()), (String::from("availability"), self.availability.clone()), (String::from("synthetic"), String::new()), (String::from("as_of"), (self.as_of.clone()).unwrap_or_default())])
    }
}

impl ReportProvenance {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("availability"), self.availability.clone()), (String::from("synthetic"), String::new()), (String::from("sources"), String::new())])
    }
}

impl RenderedReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        rendered_report_to_dict(self.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rendered_report_to_dict(mut report: RenderedReport) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("id"), report.id.clone()), (String::from("version"), report.version.clone()), (String::from("name"), report.name.clone()), (String::from("description"), report.description.clone()), (String::from("generated_at"), String::new()), (String::from("time_range"), String::new()), (String::from("variables"), String::new()), (String::from("widgets"), String::new()), (String::from("tags"), String::new()), (String::from("provenance"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rendered_widget_to_dict(mut widget: RenderedWidget) -> std::collections::BTreeMap<String, String> {
    let mut payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("id"), widget.id.clone()), (String::from("type"), widget.r#type.clone()), (String::from("title"), widget.title.clone()), (String::from("data"), String::new()), (String::from("options"), String::new())]);
    if (widget.error.clone()).is_some() {
        payload.insert(String::from("error"), (widget.error.clone()).unwrap_or_default());
    }
    payload.clone()
}

pub const PUBLIC_EXPORTS: &[&str] = &["DataSet", "DataSourceProvenance", "QuerySpec", "RenderedReport", "ReportProvenance", "RenderedWidget", "ReportSpec", "Series", "TimeGrain", "TimeRange", "Variable", "WidgetSpec"];
