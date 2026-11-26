#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RetrievalFailureLayer {
    #[default]
    StaleGeneration,
    MissingConcept,
    MappingGap,
    RankingError,
    Ambiguity,
    InactiveRule,
    ProviderEvidence,
    Presentation,
    Unknown,
}

impl RetrievalFailureLayer {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::StaleGeneration => "stale_generation",
            Self::MissingConcept => "missing_concept",
            Self::MappingGap => "mapping_gap",
            Self::RankingError => "ranking_error",
            Self::Ambiguity => "ambiguity",
            Self::InactiveRule => "inactive_rule",
            Self::ProviderEvidence => "provider_evidence",
            Self::Presentation => "presentation",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct QueryFailureEvidence {
    pub attempt_id: String,
    pub query_digest: String,
    pub principal_scope_digest: String,
    pub catalog_digest: String,
    pub reason_code: String,
    pub layer: RetrievalFailureLayer,
    pub reproduced: bool,
    pub evidence_refs: Vec<String>,
    pub exact_target_rule_ref: Option<String>,
    pub user_correction_ref: Option<String>,
    pub raw_text_retained: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SemanticFeedbackCandidate {
    pub candidate_id: String,
    pub attempt_id: String,
    pub query_digest: String,
    pub target_rule_ref: String,
    pub failure_layer: RetrievalFailureLayer,
    pub evidence_refs: Vec<String>,
    pub mode: String,
    pub promotion_authority: bool,
}

pub const DIGEST: &str = "^sha256:[a-f0-9]{64}$";
pub const IDENTIFIER: &str = "^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,511}$";
pub trait SemanticFeedbackCandidateSink {
    fn put(&self, candidate: SemanticFeedbackCandidate) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn query_failure_evidence_from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> Result<QueryFailureEvidence, &'static str> {
    let required: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("attempt_id"), String::from("query_digest"), String::from("principal_scope_digest"), String::from("catalog_digest"), String::from("reason_code"), String::from("layer"), String::from("reproduced"), String::from("evidence_refs")]);
    let optional: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("exact_target_rule_ref"), String::from("user_correction_ref"), String::from("raw_text_retained")]);
    Ok(QueryFailureEvidence { attempt_id: text(raw.clone(), String::from("attempt_id")).unwrap_or_else(|_| String::new()), query_digest: text(raw.clone(), String::from("query_digest")).unwrap_or_else(|_| String::new()), principal_scope_digest: text(raw.clone(), String::from("principal_scope_digest")).unwrap_or_else(|_| String::new()), catalog_digest: text(raw.clone(), String::from("catalog_digest")).unwrap_or_else(|_| String::new()), reason_code: text(raw.clone(), String::from("reason_code")).unwrap_or_else(|_| String::new()), exact_target_rule_ref: optional_text(raw.clone(), String::from("exact_target_rule_ref")).unwrap_or_else(|_| None), user_correction_ref: optional_text(raw.clone(), String::from("user_correction_ref")).unwrap_or_else(|_| None), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn query_failure_evidence_to_mapping(mut evidence: QueryFailureEvidence) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("attempt_id"), evidence.attempt_id.clone()), (String::from("query_digest"), evidence.query_digest.clone()), (String::from("principal_scope_digest"), evidence.principal_scope_digest.clone()), (String::from("catalog_digest"), evidence.catalog_digest.clone()), (String::from("reason_code"), evidence.reason_code.clone()), (String::from("layer"), String::new()), (String::from("reproduced"), String::new()), (String::from("evidence_refs"), String::new()), (String::from("exact_target_rule_ref"), (evidence.exact_target_rule_ref.clone()).unwrap_or_default()), (String::from("user_correction_ref"), (evidence.user_correction_ref.clone()).unwrap_or_default()), (String::from("raw_text_retained"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn build_feedback_candidate(mut evidence: QueryFailureEvidence) -> Result<SemanticFeedbackCandidate, &'static str> {
    if !(evidence.reproduced) {
        return Err("semantic retrieval failure MUST be reproduced");
    }
    if (evidence.exact_target_rule_ref.clone()).is_none() {
        return Err("semantic feedback requires an exact target Rule");
    }
    let payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("attempt_id"), evidence.attempt_id.clone()), (String::from("query_digest"), evidence.query_digest.clone()), (String::from("target_rule_ref"), (evidence.exact_target_rule_ref.clone()).unwrap_or_default()), (String::from("failure_layer"), String::new()), (String::from("evidence_refs"), String::new())]);
    Ok(SemanticFeedbackCandidate { attempt_id: evidence.attempt_id.clone(), query_digest: evidence.query_digest.clone(), target_rule_ref: (evidence.exact_target_rule_ref.clone()).unwrap_or_default(), failure_layer: evidence.layer.clone(), evidence_refs: evidence.evidence_refs.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn identifier(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn digest(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn text(mut raw: std::collections::BTreeMap<String, String>, mut name: String) -> Result<String, &'static str> {
    let value: Option<String> = (raw.clone()).get(name.as_str()).cloned();
    if (!(true)) || (!((value.clone()).is_some())) {
        return Err("query failure evidence name MUST be a non-empty string");
    }
    Ok((value.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn optional_text(mut raw: std::collections::BTreeMap<String, String>, mut name: String) -> Result<Option<String>, &'static str> {
    let value: Option<String> = (raw.clone()).get(name.as_str()).cloned();
    let Some(mut value) = value.clone() else { return Ok(None); };
    if (!(true)) || ((value.clone()).is_empty()) {
        return Err("query failure evidence name MUST be null or non-empty string");
    }
    Ok(Some(value.clone()))
}

pub const PUBLIC_EXPORTS: &[&str] = &["QueryFailureEvidence", "RetrievalFailureLayer", "SemanticFeedbackCandidate", "SemanticFeedbackCandidateSink", "build_feedback_candidate", "query_failure_evidence_from_mapping", "query_failure_evidence_to_mapping"];
