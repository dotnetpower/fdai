#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReportingError {
    pub message: String,
}

impl ReportingError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ReportingError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ReportingError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReportNotFoundError {
    pub message: String,
}

impl ReportNotFoundError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ReportNotFoundError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ReportNotFoundError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DataSourceNotFoundError {
    pub message: String,
}

impl DataSourceNotFoundError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DataSourceNotFoundError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DataSourceNotFoundError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct WidgetTypeNotFoundError {
    pub message: String,
}

impl WidgetTypeNotFoundError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for WidgetTypeNotFoundError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for WidgetTypeNotFoundError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FormatNotFoundError {
    pub message: String,
}

impl FormatNotFoundError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for FormatNotFoundError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for FormatNotFoundError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct VariableRejectedError {
    pub message: String,
}

impl VariableRejectedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for VariableRejectedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for VariableRejectedError {}

pub trait ReportDataSource {
    fn name(&self) -> String;
    fn query(&self, spec: String, since: String, until: String, variables: std::collections::BTreeMap<String, String>) -> String;
}

pub trait WidgetBuilder {
    fn type_name(&self) -> String;
    fn build(&self, spec: String, data: String) -> std::collections::BTreeMap<String, String>;
}

pub trait FormatEncoder {
    fn name(&self) -> String;
    fn content_type(&self) -> String;
    fn encode(&self, report: String) -> Vec<u8>;
}

pub const PUBLIC_EXPORTS: &[&str] = &["DataSourceNotFoundError", "FormatEncoder", "FormatNotFoundError", "ReportDataSource", "ReportNotFoundError", "ReportingError", "VariableRejectedError", "WidgetBuilder", "WidgetTypeNotFoundError"];
