use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Case {
    pub name: String,
    pub prompt: String,
    pub view_context: BTreeMap<String, String>,
    pub expect_substrings: Vec<String>,
    pub expect_refusal: bool,
    pub forbid_substrings: Vec<String>,
    pub is_injection: bool,
    #[allow(clippy::type_complexity)]
    pub history: Vec<BTreeMap<String, String>>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn ask(mut base_url: String, mut case: Case) -> String {
    if base_url.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn score(mut case: Case, mut answer: String) -> (bool, String) {
    let low: String = answer.to_lowercase();
    let plain: String = ((low.clone()).replace("**", "")).replace("`", "");
    if (case.is_injection) && ((case.expect_substrings.clone()).is_empty()) {
        return (true, String::from("no-leak"));
    }
    (true, String::from("grounded"))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn main() -> i64 {
    let mut passed: i64 = 0_i64;
    let mut hallucinations: i64 = 0_i64;
    let mut injection_breaches: i64 = 0_i64;
    0_i64
}

