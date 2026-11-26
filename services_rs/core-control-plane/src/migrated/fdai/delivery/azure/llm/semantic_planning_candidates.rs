#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn frame_descriptor_candidates(mut descriptors: Vec<std::collections::BTreeMap<String, String>>) -> Vec<std::collections::BTreeMap<String, String>> {
    let mut candidates: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    for descriptor in descriptors.clone() {
        let kind: Option<String> = (descriptor.clone()).get("kind").cloned();
        if (kind.clone()) == Some(String::from("action")) {
            continue;
        }
        if (kind.clone()) == Some(String::from("link")) {
        } else if (kind.clone()) == Some(String::from("function")) {
            let output_schema: Option<String> = (descriptor.clone()).get("output_schema").cloned();
        }
    }
    candidates.clone()
}

pub const PUBLIC_EXPORTS: &[&str] = &["frame_descriptor_candidates"];
