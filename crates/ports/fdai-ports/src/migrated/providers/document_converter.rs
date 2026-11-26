#[derive(Clone, Debug, Default, PartialEq)]
pub struct DocumentConversionRequest {
    pub converter_id: String,
    pub source_ref: String,
    pub source_suffix: String,
    pub content: Vec<u8>,
    pub max_output_bytes: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DocumentConversionResult {
    pub text: String,
}

impl DocumentConversionResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.text.trim().is_empty() { return Err("text must be non-empty"); }
        Ok(())
    }
}

pub const CONVERTER_ID: &str = "^[a-z][a-z0-9.-]{2,127}$";
pub const SUFFIX: &str = "^\\.[a-z0-9]{1,15}$";
pub trait DocumentConverter {
    fn convert(&self, request: DocumentConversionRequest) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["DocumentConversionRequest", "DocumentConversionResult", "DocumentConverter"];
