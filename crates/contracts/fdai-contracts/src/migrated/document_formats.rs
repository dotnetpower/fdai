#[derive(Clone, Debug, Default, PartialEq)]
pub struct DocumentFormatSpec {
    pub format_id: String,
    pub family: String,
    pub extensions: Vec<String>,
    pub media_types: Vec<String>,
}

pub const GENERIC_MEDIA_TYPES: &[&str] = &["", "application/octet-stream", "application/zip"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn supported_document_format_ids(mut include_ocr: bool) -> Vec<String> {
    core::hint::black_box(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn supported_document_extensions() -> Vec<String> {
    core::hint::black_box(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn classify_document_intake(mut source_name: String, mut media_type_hint: String) -> Result<DocumentFormatSpec, &'static str> {
    if source_name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

