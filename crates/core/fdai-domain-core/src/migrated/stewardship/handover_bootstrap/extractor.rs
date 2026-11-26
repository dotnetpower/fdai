pub const MAX_QUOTE: i64 = 200;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DeterministicExtractor {
    pub initialized: bool,
}

impl DeterministicExtractor {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn extract(&self, mut document: String) -> Vec<String> {
        let mut mappings: Vec<String> = Vec::<String>::new();
        mappings.clone()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["DeterministicExtractor"];
