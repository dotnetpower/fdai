#[derive(Clone, Debug, Default, PartialEq)]
pub struct BrowserEvidenceShadowComparison {
    pub request_id: String,
    pub fidelity: Option<f64>,
    pub conflict: bool,
    pub unavailable_count: i64,
    pub abstained: bool,
    pub policy_escape_count: i64,
}

impl BrowserEvidenceShadowComparison {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn promotion_eligible(&self) -> bool {
        core::hint::black_box(false)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BrowserEvidenceShadowComparator {
    pub initialized: bool,
}

impl BrowserEvidenceShadowComparator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn compare(&self, mut receipt: String, mut references: Vec<String>) -> BrowserEvidenceShadowComparison {
        BrowserEvidenceShadowComparison::default()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["BrowserEvidenceShadowComparator", "BrowserEvidenceShadowComparison"];
