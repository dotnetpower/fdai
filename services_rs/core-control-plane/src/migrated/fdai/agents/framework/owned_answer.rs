#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub async fn compose_owned_answer(mut deliberator: String, mut question: String, mut correlation_id: String, mut primary_agent: String, mut answer: std::collections::BTreeMap<String, String>, mut contributors: Vec<std::collections::BTreeMap<String, String>>, mut locale: String, mut incomplete: bool) -> std::collections::BTreeMap<String, String> {
    let result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("status"), String::from("held")), (String::from("authority"), String::from("presentation_only")), (String::from("conclusion"), String::new()), (String::from("purpose"), String::from("owned_answer")), (String::from("t2_status"), String::from("unavailable"))]);
    if incomplete {
        return std::collections::BTreeMap::from([(String::from("t2_status"), String::from("participant_evidence_incomplete"))]);
    }
    std::collections::BTreeMap::new()
}

