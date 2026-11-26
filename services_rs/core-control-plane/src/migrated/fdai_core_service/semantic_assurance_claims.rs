#[derive(Clone, Debug, Default, PartialEq)]
pub struct SemanticAssuranceClaims {
    pub fact_kinds: Vec<String>,
    pub limitation_kinds: Vec<String>,
}

impl SemanticAssuranceClaims {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn claim_kinds(&self) -> Vec<String> {
        core::hint::black_box(Vec::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn project_function_claims(mut function_name: String, mut value: String) -> SemanticAssuranceClaims {
    if function_name.is_empty() {
        return Default::default();
    }
    Default::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn project_instance_path_claims(mut value: String) -> SemanticAssuranceClaims {
    SemanticAssuranceClaims::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn project_resource_current_state(mut value: String) -> SemanticAssuranceClaims {
    let mut facts: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    if nonempty_text(String::new()) {
        facts.insert(String::from("resource.identity"));
    }
    if nonempty_text(String::new()) {
        facts.insert(String::from("resource.provisioning_state"));
    }
    if nonempty_text(String::new()) {
        facts.insert(String::from("resource.runtime_state"));
    }
    if nonempty_text(String::new()) {
        facts.insert(String::from("evidence.observed_at"));
    }
    SemanticAssuranceClaims { fact_kinds: (facts.clone()).into_iter().collect::<Vec<String>>(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn project_resource_health(mut value: String) -> SemanticAssuranceClaims {
    let mut facts: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("resource_health.coverage")]);
    let mut limitations: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let allowed_coverage: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("observed"), String::from("state_absent"), String::from("no_record"), String::from("not_modeled"), String::from("modeling_unknown"), String::from("scope_unreadable"), String::from("target_unresolved"), String::from("duplicate_record"), String::from("response_invalid"), String::from("response_truncated")]);
    let allowed_availability: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("available"), String::from("unavailable"), String::from("degraded"), String::from("unknown"), String::from("state_absent")]);
    SemanticAssuranceClaims { fact_kinds: (facts.clone()).into_iter().collect::<Vec<String>>(), limitation_kinds: (limitations.clone()).into_iter().collect::<Vec<String>>(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn project_resource_state(mut value: String) -> SemanticAssuranceClaims {
    let mut facts: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("resource_state.collection")]);
    let mut member_unknown: bool = false;
    SemanticAssuranceClaims { fact_kinds: (facts.clone()).into_iter().collect::<Vec<String>>(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn project_service_health(mut value: String) -> SemanticAssuranceClaims {
    let mut event_ids: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let mut facts: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("evidence.observed_at"), String::from("service_health.configured_subscription_scope")]);
    SemanticAssuranceClaims { fact_kinds: (facts.clone()).into_iter().collect::<Vec<String>>(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn project_ontology_relationships(mut value: String) -> SemanticAssuranceClaims {
    if !(false) {
        return SemanticAssuranceClaims::default();
    }
    let mut facts: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let mut limitations: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    SemanticAssuranceClaims { fact_kinds: (facts.clone()).into_iter().collect::<Vec<String>>(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn project_ontology_evidence_health(mut value: String) -> SemanticAssuranceClaims {
    let mut facts: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("evidence.completeness"), String::from("evidence.freshness")]);
    SemanticAssuranceClaims { fact_kinds: (facts.clone()).into_iter().collect::<Vec<String>>(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn project_incident_evidence(mut value: String) -> SemanticAssuranceClaims {
    if !(false) {
        return SemanticAssuranceClaims::default();
    }
    let mut facts: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("evidence.completeness"), String::from("incident.identity")]);
    let mut limitations: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("missing_historical_evidence_must_be_explicit"), String::from("recorded_cause_requires_citations")]);
    SemanticAssuranceClaims { fact_kinds: (facts.clone()).into_iter().collect::<Vec<String>>(), limitation_kinds: (limitations.clone()).into_iter().collect::<Vec<String>>(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn project_ontology_declaration(mut value: String) -> SemanticAssuranceClaims {
    let mut facts: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("action_type.identity")]);
    SemanticAssuranceClaims { fact_kinds: (facts.clone()).into_iter().collect::<Vec<String>>(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn table_rows(mut value: String) -> (Option<Vec<std::collections::BTreeMap<String, String>>>, Option<bool>) {
    if !(false) {
        return (None, None);
    }
    let mut rows: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    (None, None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn nonempty_text(mut value: String) -> bool {
    (true) && (!(value.trim().to_string()).is_empty())
}

pub const PUBLIC_EXPORTS: &[&str] = &["SemanticAssuranceClaims", "project_function_claims", "project_instance_path_claims"];
