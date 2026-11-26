pub trait CrossVerticalPrecedence {
    fn winner(&self, domains: Vec<String>) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InitialVerticalPrecedence {
    pub initialized: bool,
}

impl InitialVerticalPrecedence {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn winner(&self, mut domains: Vec<String>) -> Option<String> {
        let mut normalized_pairs: Vec<(String, String)> = Vec::<(String, String)>::new();
        let mut seen_keys: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
        for raw_domain in domains.clone() {
            let original: String = (raw_domain.clone()).trim().to_string();
            let key: String = (original.clone()).to_lowercase();
            if (!(original.clone()).is_empty()) && (!((seen_keys.clone()).contains(key.as_str()))) {
                seen_keys.insert(key.clone());
                normalized_pairs.push((original.clone(), key.clone()));
            }
        }
        if (((normalized_pairs.clone()).len() as i64)) < (2_i64) {
            return None;
        }
        None
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["CrossVerticalPrecedence", "InitialVerticalPrecedence"];
