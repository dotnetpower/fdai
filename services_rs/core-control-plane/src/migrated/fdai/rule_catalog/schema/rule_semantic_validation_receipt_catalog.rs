#[derive(Clone, Debug, Default, PartialEq)]
pub struct SemanticValidationReceiptCatalogIssue {
    pub key: String,
    pub message: String,
}

pub const SCHEMA_FILE: &str = "rule_semantic_validation_receipt.schema.json";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SemanticValidationReceiptCatalogError {
    pub message: String,
}

impl SemanticValidationReceiptCatalogError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for SemanticValidationReceiptCatalogError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SemanticValidationReceiptCatalogError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_semantic_validation_receipts(mut root: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut issues: Vec<SemanticValidationReceiptCatalogIssue> = Vec::<SemanticValidationReceiptCatalogIssue>::new();
    let mut loaded: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    if !(issues.clone()).is_empty() {
        return Err("issues");
    }
    Ok(loaded.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn receipt_from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> String {
    if raw.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn schema() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["SemanticValidationReceiptCatalogError", "SemanticValidationReceiptCatalogIssue", "load_semantic_validation_receipts"];
