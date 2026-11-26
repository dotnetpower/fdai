use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ParserName {
    #[default]
    RuleYaml,
    Rego,
    AzurePolicyJson,
    CheckovYaml,
    KubeBench,
    GatekeeperTemplates,
}

impl ParserName {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::RuleYaml => "rule-yaml",
            Self::Rego => "rego",
            Self::AzurePolicyJson => "azure-policy-json",
            Self::CheckovYaml => "checkov-yaml",
            Self::KubeBench => "kube-bench",
            Self::GatekeeperTemplates => "gatekeeper-templates",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ParsedRule {
    pub origin: String,
    pub raw: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ParseReport {
    pub parser: ParserName,
    pub rules: Vec<ParsedRule>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ParseError {
    pub message: String,
}

impl ParseError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ParseError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ParserNotImplementedError {
    pub message: String,
}

impl ParserNotImplementedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ParserNotImplementedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ParserNotImplementedError {}

impl ParseReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn rule_count(&self) -> i64 {
        (self.rules.clone()).len() as i64
    }
}

pub trait Parser {
    fn name(&self) -> ParserName;
    fn parse(&self, snapshot_tree_root: String) -> ParseReport;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn build_parser(mut name: String) -> Result<String, &'static str> {
    if true {
    } else {
        let mut resolved: String = name.clone();
    }
    Err("parser resolved.valuer is declared in the manifest schema but  has no bu")
}

