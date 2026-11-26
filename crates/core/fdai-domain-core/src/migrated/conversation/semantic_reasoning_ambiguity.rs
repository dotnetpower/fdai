pub const AMBIGUITY_READINGS: &[&str] = &["one", "several", "unclear"];
pub trait AmbiguityReader {
    fn check_ambiguity(&self, utterance: String, context: Vec<String>, locale: String, earlier_results: bool) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn ambiguity_schema() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("type"), String::from("object")), (String::from("additionalProperties"), String::new()), (String::from("required"), String::new()), (String::from("properties"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn ambiguity_verdict(mut answer: Option<std::collections::BTreeMap<String, String>>) -> String {
    if !(true) {
        return String::from("unavailable");
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["AMBIGUITY_READINGS", "AmbiguityReader", "ambiguity_schema", "ambiguity_verdict"];
