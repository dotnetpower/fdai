pub trait RuleRevisionRetirementAuthorizer {
    fn authorize_retirement(&self, approval: String, proposal: String) -> String;
}

pub trait RuleRevisionRegistryReader {
    fn has_retained_closure(&self, revision: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["RuleRevisionRegistryReader", "RuleRevisionRetirementAuthorizer"];
