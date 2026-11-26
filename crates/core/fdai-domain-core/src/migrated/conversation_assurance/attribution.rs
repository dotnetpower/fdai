pub const MAX_STRUCTURAL_EVIDENCE_REFS: i64 = 64;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum FailureLayer {
    #[default]
    Context,
    Evidence,
    Routing,
    Rendering,
    Policy,
    Rule,
    OntologyMapping,
    OntologyProjection,
    OntologySchema,
    Dynamic,
    Unknown,
}

impl FailureLayer {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Context => "context",
            Self::Evidence => "evidence",
            Self::Routing => "routing",
            Self::Rendering => "rendering",
            Self::Policy => "policy",
            Self::Rule => "rule",
            Self::OntologyMapping => "ontology_mapping",
            Self::OntologyProjection => "ontology_projection",
            Self::OntologySchema => "ontology_schema",
            Self::Dynamic => "dynamic",
            Self::Unknown => "unknown",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ConversationStage {
    #[default]
    ContextFraming,
    Routing,
    EvidenceRetrieval,
    ToolExecution,
    Synthesis,
    Rendering,
    Transport,
}

impl ConversationStage {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ContextFraming => "context_framing",
            Self::Routing => "routing",
            Self::EvidenceRetrieval => "evidence_retrieval",
            Self::ToolExecution => "tool_execution",
            Self::Synthesis => "synthesis",
            Self::Rendering => "rendering",
            Self::Transport => "transport",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum StageOutcome {
    #[default]
    Passed,
    Failed,
    Unavailable,
    NotApplicable,
}

impl StageOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Passed => "passed",
            Self::Failed => "failed",
            Self::Unavailable => "unavailable",
            Self::NotApplicable => "not_applicable",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AdequacyCandidateKind {
    #[default]
    ProviderMapping,
    ProjectionBinding,
    OntologyDeclaration,
    RuleCandidate,
    DynamicModel,
}

impl AdequacyCandidateKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ProviderMapping => "provider_mapping",
            Self::ProjectionBinding => "projection_binding",
            Self::OntologyDeclaration => "ontology_declaration",
            Self::RuleCandidate => "rule_candidate",
            Self::DynamicModel => "dynamic_model",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AdequacyReviewState {
    #[default]
    NotApplicable,
    Held,
    Ready,
}

impl AdequacyReviewState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::NotApplicable => "not_applicable",
            Self::Held => "held",
            Self::Ready => "ready",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StructuralStageObservation {
    pub stage: ConversationStage,
    pub outcome: StageOutcome,
    pub reason_code: String,
    pub evidence_refs: Vec<String>,
}

impl StructuralStageObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.reason_code.trim().is_empty() { return Err("reason_code must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StructuralFailureAttribution {
    pub attribution_id: String,
    pub turn_id: String,
    pub root_stage: Option<ConversationStage>,
    pub contributing_stages: Vec<ConversationStage>,
    pub failed_rubrics: Vec<String>,
    pub reason_codes: Vec<String>,
    pub evidence_refs: Vec<String>,
    pub channel_kind: Option<String>,
    pub locale: Option<String>,
    pub route_id: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StructuralFailureSummary {
    pub total_failures: i64,
    pub root_stage_counts: Vec<String>,
    pub failed_rubric_counts: Vec<String>,
    pub reason_code_counts: Vec<String>,
    pub channel_counts: Vec<String>,
    pub locale_counts: Vec<String>,
    pub route_counts: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnswerFailureAttribution {
    pub attribution_id: String,
    pub turn_id: String,
    pub reason_code: String,
    pub layer: FailureLayer,
    pub evidence_refs: Vec<String>,
    pub evidence_complete: Option<bool>,
    pub route_id: Option<String>,
    pub ontology_release: Option<String>,
    pub graph_revision: Option<String>,
    pub reason: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyAdequacyReview {
    pub review_id: String,
    pub attribution_id: String,
    pub state: AdequacyReviewState,
    pub candidate_kind: Option<AdequacyCandidateKind>,
    pub competency_question_digest: String,
    pub ontology_release: Option<String>,
    pub graph_revision: Option<String>,
    pub evidence_refs: Vec<String>,
    pub reason_codes: Vec<String>,
}

pub trait OntologyAdequacyInvestigator {
    fn investigate(&self, turn: String, attribution: AnswerFailureAttribution) -> String;
}

pub trait OntologyAdequacyReviewSink {
    fn submit(&self, review: OntologyAdequacyReview) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HoldingOntologyAdequacyInvestigator {
    pub initialized: bool,
}

impl HoldingOntologyAdequacyInvestigator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn investigate(&self, mut turn: String, mut attribution: AnswerFailureAttribution) -> OntologyAdequacyReview {
        build_ontology_adequacy_review(attribution.clone(), String::new(), false, false, false)
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn attribute_answer_failure(mut turn: String) -> AnswerFailureAttribution {
    let layer: FailureLayer = layer_for_reason(String::new());
    AnswerFailureAttribution { layer: layer.clone(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_ontology_adequacy_review(mut attribution: AnswerFailureAttribution, mut question_digest: String, mut replay_reproduced: bool, mut routing_verified: bool, mut identity_resolved: bool) -> OntologyAdequacyReview {
    let candidate_kind: Option<AdequacyCandidateKind> = candidate_kind(attribution.layer.clone());
    let mut reasons: Vec<String> = Vec::<String>::new();
    if candidate_kind.is_none() {
        reasons.push(String::from("failure_owned_by_other_layer"));
    } else {
        if !(routing_verified) {
            reasons.push(String::from("routing_unverified"));
        }
        if !(identity_resolved) {
            reasons.push(String::from("identity_unresolved"));
        }
        if !(replay_reproduced) {
            reasons.push(String::from("gap_not_reproduced"));
        }
        if (attribution.ontology_release.clone()).is_none() {
            reasons.push(String::from("ontology_release_unavailable"));
        }
        if (attribution.graph_revision.clone()).is_none() {
            reasons.push(String::from("graph_revision_unavailable"));
        }
    }
    OntologyAdequacyReview { attribution_id: attribution.attribution_id.clone(), candidate_kind: candidate_kind.clone(), competency_question_digest: question_digest.clone(), ontology_release: attribution.ontology_release.clone(), graph_revision: attribution.graph_revision.clone(), evidence_refs: attribution.evidence_refs.clone(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn attribute_structural_failure(mut turn_id: String, mut answer_digest: String, mut observations: Vec<StructuralStageObservation>, mut failed_rubrics: Vec<String>, mut channel_kind: Option<String>, mut locale: Option<String>, mut route_id: Option<String>) -> Result<StructuralFailureAttribution, &'static str> {
    if ((turn_id.trim().to_string()).is_empty()) || (((answer_digest.clone()).trim().to_string()).is_empty()) {
        return Err("structural attribution identity fields MUST be non-empty");
    }
    let mut by_stage: std::collections::BTreeMap<String, StructuralStageObservation> = std::collections::BTreeMap::<String, StructuralStageObservation>::new();
    Ok(StructuralFailureAttribution { turn_id: turn_id.clone(), channel_kind: channel_kind.clone(), locale: locale.clone(), route_id: route_id.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn aggregate_structural_failures(mut attributions: Vec<StructuralFailureAttribution>) -> StructuralFailureSummary {
    let mut stage_counts: std::collections::BTreeMap<String, i64> = std::collections::BTreeMap::<String, i64>::new();
    let mut rubric_counts: std::collections::BTreeMap<String, i64> = std::collections::BTreeMap::<String, i64>::new();
    let mut reason_counts: std::collections::BTreeMap<String, i64> = std::collections::BTreeMap::<String, i64>::new();
    let channel_counts: std::collections::BTreeMap<String, i64> = std::collections::BTreeMap::<String, i64>::new();
    let locale_counts: std::collections::BTreeMap<String, i64> = std::collections::BTreeMap::<String, i64>::new();
    let route_counts: std::collections::BTreeMap<String, i64> = std::collections::BTreeMap::<String, i64>::new();
    for attribution in attributions.clone() {
        for rubric in attribution.failed_rubrics.clone() {
            rubric_counts.insert(rubric.clone(), ((rubric_counts.clone()).get(rubric.as_str()).cloned().unwrap_or_else(|| 0_i64)).saturating_add(1_i64));
        }
        for reason in attribution.reason_codes.clone() {
            reason_counts.insert(reason.clone(), ((reason_counts.clone()).get(reason.as_str()).cloned().unwrap_or_else(|| 0_i64)).saturating_add(1_i64));
        }
    }
    StructuralFailureSummary::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn layer_for_reason(mut reason: String) -> FailureLayer {
    if reason.is_empty() {
        return Default::default();
    }
    Default::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn candidate_kind(mut layer: FailureLayer) -> Option<AdequacyCandidateKind> {
    core::hint::black_box(None)
}

pub const PUBLIC_EXPORTS: &[&str] = &["AdequacyCandidateKind", "AdequacyReviewState", "AnswerFailureAttribution", "ConversationStage", "FailureLayer", "HoldingOntologyAdequacyInvestigator", "OntologyAdequacyInvestigator", "OntologyAdequacyReview", "OntologyAdequacyReviewSink", "StageOutcome", "StructuralFailureAttribution", "StructuralFailureSummary", "StructuralStageObservation", "aggregate_structural_failures", "attribute_answer_failure", "attribute_structural_failure", "build_ontology_adequacy_review"];
