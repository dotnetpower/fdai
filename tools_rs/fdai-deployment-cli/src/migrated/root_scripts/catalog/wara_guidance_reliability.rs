#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn localized(mut en: String, mut ko: Option<String>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("en"), en.clone())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::too_many_arguments)]
pub fn profile(mut shape: String, mut rationale: (String, String), mut applies: (String, String), mut before: (String, String), mut after: (String, String), mut configure: (String, String), mut verify: (String, String), mut caution: (String, String)) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("shape"), shape.clone())])
}

