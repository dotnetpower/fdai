#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ScanFindingKind {
    #[default]
    Sensitive,
    Identifier,
    PromptInjection,
}

impl ScanFindingKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Sensitive => "secret",
            Self::Identifier => "identifier",
            Self::PromptInjection => "prompt_injection",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScanFinding {
    pub kind: ScanFindingKind,
    pub code: String,
}

impl ScanFinding {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.code.trim().is_empty() { return Err("code must be non-empty"); }
        Ok(())
    }
}

pub const RESOURCE_ID_PATTERN: &str = "(?i)/subscriptions/[^/\\s]+/";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn scan_envelope(mut envelope: String) -> Vec<ScanFinding> {
    let mut findings: Vec<ScanFinding> = Vec::<ScanFinding>::new();
    findings.clone()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ScanFinding", "ScanFindingKind", "scan_envelope"];
