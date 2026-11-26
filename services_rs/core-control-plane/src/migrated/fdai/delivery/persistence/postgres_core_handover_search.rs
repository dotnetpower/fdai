#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresCoreHandoverSearch {
    pub source: String,
    pub goals: String,
    pub goal: String,
}

impl PostgresCoreHandoverSearch {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn search(&self, mut query: String, mut collection_id: String, mut allowed_access_refs: std::collections::BTreeSet<String>, mut k: i64) -> Result<Vec<String>, &'static str> {
        let statement: String = String::from("SELECT * FROM fdai_search_core_handover_goal(%s,%s,%s,%s,%s,%s,%s)");
        Ok(Vec::new())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresCoreHandoverSearch"];
