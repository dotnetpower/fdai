#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProcedureVerdict {
    #[default]
    Procedure,
    NotProcedure,
    Uncertain,
}

impl ProcedureVerdict {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Procedure => "procedure",
            Self::NotProcedure => "not_procedure",
            Self::Uncertain => "uncertain",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ClassifiedManual {
    pub candidate: String,
    pub verdict: ProcedureVerdict,
    pub confidence: f64,
}

pub trait ManualClassifier {
    fn classify(&self, candidates: Vec<String>) -> Vec<ClassifiedManual>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AbstainingManualClassifier {
    pub initialized: bool,
}

impl AbstainingManualClassifier {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn classify(&self, mut candidates: Vec<String>) -> Vec<ClassifiedManual> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AbstainingManualClassifier", "ClassifiedManual", "ManualClassifier", "ProcedureVerdict"];
