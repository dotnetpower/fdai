#[derive(Clone, Debug, Default, PartialEq)]
pub struct DocumentParserPolicy {
    pub max_input_bytes: i64,
    pub max_units: i64,
    pub max_text_characters: i64,
    pub max_markdown_tokens: i64,
    pub max_markdown_nesting: i64,
    pub max_sgml_nesting: i64,
    pub max_ooxml_members: i64,
    pub max_ooxml_expanded_bytes: i64,
    pub max_ooxml_compression_ratio: f64,
    pub max_ooxml_xml_member_bytes: i64,
    pub max_ooxml_xml_depth: i64,
    pub max_pdf_pages: i64,
    pub max_pdf_objects: i64,
    pub max_pdf_raw_stream_bytes: i64,
    pub max_pdf_decoded_stream_bytes: i64,
    pub max_pdf_units: i64,
    pub max_pdf_characters: i64,
    pub max_ocr_pages: i64,
    pub max_ocr_units: i64,
    pub max_ocr_characters: i64,
}

pub const PUBLIC_EXPORTS: &[&str] = &["DEFAULT_DOCUMENT_PARSER_POLICY", "DocumentParserPolicy"];
