#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MuninnPatternReadMixin {
    pub initialized: bool,
}

impl MuninnPatternReadMixin {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn read_operating_pattern(&self, mut cohort_key: String, mut pattern_id: String, mut access_scope_digest: String, mut purpose: String) -> Option<std::collections::BTreeMap<String, String>> {
        self.read_operating_pattern_1(cohort_key.clone(), pattern_id.clone(), access_scope_digest.clone(), purpose.clone()).await
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn read_operating_pattern_1(&self, mut cohort_key: String, mut pattern_id: String, mut access_scope_digest: String, mut purpose: String) -> Option<std::collections::BTreeMap<String, String>> {
        let prefix: String = String::from("operational-case-fingerprint-cohort:v2:");
        if (!((cohort_key.clone()).starts_with(prefix.as_str()))) || ((((cohort_key.clone()).len() as i64)) != ((((prefix.clone()).len() as i64)).saturating_add(64_i64))) {
            return None;
        }
        if (((purpose.clone()).trim().to_string()).is_empty()) || ((((purpose.clone()).len() as i64)) > (512_i64)) {
            return None;
        }
        let key: String = format!("{}:pattern:{}", cohort_key.clone(), pattern_id.clone());
        None
    }
}

