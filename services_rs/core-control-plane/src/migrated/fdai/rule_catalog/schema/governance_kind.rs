#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum GovernanceKind {
    #[default]
    RuleSet,
    Assignment,
    Exemption,
    Override,
}

impl GovernanceKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::RuleSet => "rule-set",
            Self::Assignment => "assignment",
            Self::Exemption => "exemption",
            Self::Override => "override",
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["GovernanceKind"];
