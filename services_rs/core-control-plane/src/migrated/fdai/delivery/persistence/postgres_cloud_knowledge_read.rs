#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresCloudKnowledgeRead {
    pub initialized: bool,
}

impl PostgresCloudKnowledgeRead {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn resolve(&self, mut binding: String, mut source_id: String, mut now: String) -> Result<(String, bool), &'static str> {
        Ok((String::new(), false))
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn policy_bytes(mut path: String) -> Result<Vec<u8>, &'static str> {
    if path.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

