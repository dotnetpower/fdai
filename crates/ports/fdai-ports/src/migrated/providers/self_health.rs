#[derive(Clone, Debug, Default, PartialEq)]
pub struct SelfHealthExportSample {
    pub signal: String,
    pub value: i64,
    pub observed_at: String,
    pub source: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SelfHealthExporterUnavailableError {
    pub message: String,
}

impl SelfHealthExporterUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for SelfHealthExporterUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SelfHealthExporterUnavailableError {}

pub trait SelfHealthExporter {
    fn signal(&self) -> String;
}

pub trait ModelProviderObservationSource {
    fn role(&self) -> String;
}

pub trait ModelProviderObservedProvider {
    fn model_provider_observations(&self, maximum_age_seconds: i64) -> String;
}

pub trait ModelProviderScopeSource {
    fn registration(&self) -> String;
}

pub trait OperationalStateFieldExporter {
    fn field_name(&self) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["OperationalStateFieldExporter", "SelfHealthExportSample", "SelfHealthExporter", "SelfHealthExporterUnavailableError", "ModelProviderObservationSource", "ModelProviderObservedProvider", "ModelProviderScopeSource"];
