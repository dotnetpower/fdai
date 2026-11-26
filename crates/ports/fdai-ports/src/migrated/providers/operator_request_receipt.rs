pub trait OperatorRequestReceiptIssuer {
    fn attach(&self, event: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String>;
}

pub const PUBLIC_EXPORTS: &[&str] = &["OperatorRequestReceiptIssuer"];
