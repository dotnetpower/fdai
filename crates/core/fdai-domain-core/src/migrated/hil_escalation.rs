#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EscalationDuty {
    #[default]
    Primary,
    Backup,
    Escalation,
    Maintainer,
}

impl EscalationDuty {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Primary => "primary",
            Self::Backup => "backup",
            Self::Escalation => "escalation",
            Self::Maintainer => "maintainer",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EscalationRung {
    pub subject_ref: String,
    pub duty: EscalationDuty,
    pub minimum_role: String,
}

impl EscalationRung {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.subject_ref.trim().is_empty() { return Err("subject_ref must be non-empty"); }
        if self.minimum_role.trim().is_empty() { return Err("minimum_role must be non-empty"); }
        Ok(())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["EscalationDuty", "EscalationRung"];
