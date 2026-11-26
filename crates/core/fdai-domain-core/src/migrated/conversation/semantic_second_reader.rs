#[derive(Clone, Debug, Default, PartialEq)]
pub struct SemanticSecondReader {
    pub type_grounding: Option<String>,
    pub coverage_review: Option<String>,
    pub compiled_answers: Option<String>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn planner_arguments(mut reader: Option<SemanticSecondReader>, mut gateway: Option<String>, mut purpose: Option<String>, mut clock: Option<String>) -> std::collections::BTreeMap<String, String> {
    let Some(mut reader) = reader.clone() else { return std::collections::BTreeMap::<String, String>::new(); };
    let mut arguments: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("type_grounding"), (reader.type_grounding.clone()).unwrap_or_default()), (String::from("coverage_review"), (reader.coverage_review.clone()).unwrap_or_default())]);
    arguments.clone()
}

pub const PUBLIC_EXPORTS: &[&str] = &["CompiledAnswerFactory", "SemanticSecondReader", "planner_arguments"];
