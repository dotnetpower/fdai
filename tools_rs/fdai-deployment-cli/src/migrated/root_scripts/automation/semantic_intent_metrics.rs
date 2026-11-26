#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn metric(mut name: String, mut definition: String, mut aggregation: String, mut target: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("name"), name.clone()), (String::from("definition"), definition.clone()), (String::from("aggregation"), aggregation.clone()), (String::from("promotion_target"), target.clone())])
}

