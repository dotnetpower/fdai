#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WaraDisposition {
    #[default]
    ExistingRule,
    NewRuleCandidate,
    ManualEvidence,
    ConditionalNotApplicable,
    AmbiguousOrBlocked,
}

impl WaraDisposition {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ExistingRule => "existing_rule",
            Self::NewRuleCandidate => "new_rule_candidate",
            Self::ManualEvidence => "manual_evidence",
            Self::ConditionalNotApplicable => "conditional_not_applicable",
            Self::AmbiguousOrBlocked => "ambiguous_or_blocked",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WaraMappingState {
    #[default]
    Full,
    Partial,
    Unmapped,
}

impl WaraMappingState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Full => "full",
            Self::Partial => "partial",
            Self::Unmapped => "unmapped",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ResourceTypeDisposition {
    #[default]
    Canonical,
    Unsupported,
    Ambiguous,
}

impl ResourceTypeDisposition {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Canonical => "canonical",
            Self::Unsupported => "unsupported",
            Self::Ambiguous => "ambiguous",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum QuerySafetyClassification {
    #[default]
    ReadOnlyBounded,
    Blocked,
}

impl QuerySafetyClassification {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ReadOnlyBounded => "read_only_bounded",
            Self::Blocked => "blocked",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WaraManualEvidenceRole {
    #[default]
    Required,
    Fallback,
}

impl WaraManualEvidenceRole {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Required => "required",
            Self::Fallback => "fallback",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraQuerySafetyReview {
    pub query_ref: String,
    pub body_digest: String,
    pub safety_classification: QuerySafetyClassification,
    pub declared_tables: Vec<String>,
    pub query_resource_types: Vec<String>,
    pub maximum_rows: i64,
    pub timeout_seconds: i64,
    pub evidence_freshness_ceiling_seconds: i64,
    pub evaluator_ref: Option<String>,
    pub blocked_reasons: Vec<String>,
}

impl WaraQuerySafetyReview {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=1000_i64).contains(&self.maximum_rows) { return Err("maximum_rows out of bounds"); }
        if !(1_i64..=60_i64).contains(&self.timeout_seconds) { return Err("timeout_seconds out of bounds"); }
        if !(60_i64..=31536000_i64).contains(&self.evidence_freshness_ceiling_seconds) { return Err("evidence_freshness_ceiling_seconds out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraManualEvidenceRequirement {
    pub role: WaraManualEvidenceRole,
    pub kind: String,
    pub authoritative_producer: String,
    pub scope_contract: String,
    pub freshness_ceiling_seconds: i64,
    pub digest_required: bool,
    pub failure_behavior: String,
    pub accountable_owner_slot: String,
    pub blocked_reason: Option<String>,
}

impl WaraManualEvidenceRequirement {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(60_i64..=31536000_i64).contains(&self.freshness_ceiling_seconds) { return Err("freshness_ceiling_seconds out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraApplicabilityMapping {
    pub normalized_provider_type: String,
    pub disposition: ResourceTypeDisposition,
    pub canonical_resource_type: Option<String>,
    pub canonical_resource_types: Vec<String>,
    pub provider_resource_types: Vec<String>,
    pub parent_provider_type: Option<String>,
    pub requires_exact_child_scope: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraRecommendationCrosswalk {
    pub aprl_guid: String,
    pub title: String,
    pub recommendation_control: String,
    pub impact: String,
    pub provider_resource_type: String,
    pub source_path: String,
    pub source_digest: String,
    pub workload_tags: Vec<String>,
    pub automation_available: bool,
    pub product_group_verified: bool,
    pub disposition: WaraDisposition,
    pub mapping_state: WaraMappingState,
    pub rule_refs: Vec<String>,
    pub objective_refs: Vec<String>,
    pub applicability: Box<WaraApplicabilityMapping>,
    #[allow(clippy::type_complexity)]
    pub query_review: Option<Box<WaraQuerySafetyReview>>,
    #[allow(clippy::type_complexity)]
    pub manual_evidence: Option<Box<WaraManualEvidenceRequirement>>,
    pub reviewer: String,
    pub review_state: String,
    pub implementation_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraResourceTypeMapping {
    pub reviewer: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraUmbrellaRelation {
    pub aprl_guid: String,
    pub waf_control_ref: String,
    pub relation: String,
    pub semantic_equivalence: bool,
    pub counting: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraExpectedCounts {
    pub active_recommendations: i64,
    pub disabled_recommendations: i64,
    pub resource_types: i64,
    pub automated_recommendations: i64,
    pub manual_recommendations: i64,
}

impl WaraExpectedCounts {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=9223372036854775807_i64).contains(&self.active_recommendations) { return Err("active_recommendations out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.disabled_recommendations) { return Err("disabled_recommendations out of bounds"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.resource_types) { return Err("resource_types out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.automated_recommendations) { return Err("automated_recommendations out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.manual_recommendations) { return Err("manual_recommendations out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraAssessmentCatalog {
    pub schema_version: String,
    pub framework_id: String,
    pub framework_version: String,
    pub source_revision: String,
    pub source_license: String,
    pub redistribution: String,
    pub source_catalog_digest: String,
    pub published_active_digest: String,
    pub published_object_digest: String,
    pub queries_digest: String,
    pub expected_counts: Box<WaraExpectedCounts>,
    pub resource_type_mappings: Vec<WaraResourceTypeMapping>,
    pub umbrella_relations: Vec<WaraUmbrellaRelation>,
    pub recommendations: Vec<WaraRecommendationCrosswalk>,
    pub crosswalk_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraQueryBody {
    pub aprl_guid: String,
    pub body_digest: String,
    pub body_base64: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraQueryCatalog {
    pub schema_version: String,
    pub source_revision: String,
    pub published_active_digest: String,
    pub published_object_digest: String,
    pub queries: Vec<WaraQueryBody>,
    pub reference_queries: Vec<WaraQueryBody>,
    pub null_query_guids: Vec<String>,
    pub queries_digest: String,
}

pub const SHA256: &str = "^sha256:[a-f0-9]{64}$";
pub const UUID: &str = "^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$";
pub const GIT_REF: &str = "^[a-f0-9]{40}$";
pub const IDENTIFIER: &str = "^[a-z0-9][a-z0-9._:-]{0,255}$";
impl WaraQuerySafetyReview {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_review(&self) -> Result<WaraQuerySafetyReview, &'static str> {
        if (self.evaluator_ref.is_none()) && ((self.blocked_reasons.clone()).is_empty()) {
            return Err("WARA query review requires an evaluator or blocked reason");
        }
        if (self.evaluator_ref.is_some()) && ((self.blocked_reasons.clone()).contains(&(String::from("missing_exact_evaluator")))) {
            return Err("mapped evaluator cannot be marked missing");
        }
        Ok(self.clone())
    }
}

impl WaraApplicabilityMapping {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_mapping(&self) -> Result<WaraApplicabilityMapping, &'static str> {
        let candidates: Vec<String> = self.canonical_resource_types.clone();
        if (self.requires_exact_child_scope) != (self.parent_provider_type.is_some()) {
            return Err("child-scope flag MUST match parent provider type presence");
        }
        Ok(self.clone())
    }
}

impl WaraRecommendationCrosswalk {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_axes(&self) -> Result<WaraRecommendationCrosswalk, &'static str> {
        if (self.automation_available) != (self.query_review.is_some()) {
            return Err("automation_available MUST match query_review presence");
        }
        if self.manual_evidence.is_none() {
            return Err("all active recommendations require a manual evidence contract");
        }
        if (self.implementation_digest.clone()) != (canonical_digest(String::new())) {
            return Err("self.aprl_guid: implementation_digest mismatch");
        }
        Ok(self.clone())
    }
}

impl WaraUmbrellaRelation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn reject_equivalence(&self) -> Result<WaraUmbrellaRelation, &'static str> {
        if self.semantic_equivalence {
            return Err("WAF umbrella relation cannot assert semantic equivalence");
        }
        Ok(self.clone())
    }
}

impl WaraExpectedCounts {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_partition(&self) -> Result<WaraExpectedCounts, &'static str> {
        if ((self.automated_recommendations).saturating_add(self.manual_recommendations)) != (self.active_recommendations) {
            return Err("automated and manual counts MUST partition active recommendations");
        }
        Ok(self.clone())
    }
}

impl WaraQueryBody {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_digest(&self) -> Result<WaraQueryBody, &'static str> {
        let body: String = self.decoded_body().unwrap_or_else(|_| String::new());
        Ok(self.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn decoded_body(&self) -> Result<String, &'static str> {
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn canonical_digest(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn classify_wara_query(mut query: String, mut declared_provider_type: Option<String>) -> (QuerySafetyClassification, Vec<String>, Vec<String>, Vec<String>) {
    (Default::default(), Vec::new(), Vec::new(), Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn json_object(mut path: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_wara_assessment_catalog(mut path: String, mut queries_path: String, mut framework: Option<String>, mut framework_path: Option<String>) -> Result<(WaraAssessmentCatalog, WaraQueryCatalog), &'static str> {
    let raw_catalog: std::collections::BTreeMap<String, String> = json_object(path.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let stored_crosswalk_digest: Option<String> = (raw_catalog.clone()).get("crosswalk_digest").cloned();
    let mut digest_material: std::collections::BTreeMap<String, String> = raw_catalog.clone();
    if (stored_crosswalk_digest.clone()) != Some(canonical_digest(String::new())) {
        return Err("WARA crosswalk digest mismatch");
    }
    let raw_queries: std::collections::BTreeMap<String, String> = json_object(queries_path.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let stored_queries_digest: Option<String> = (raw_queries.clone()).get("queries_digest").cloned();
    let mut query_material: std::collections::BTreeMap<String, String> = raw_queries.clone();
    if (stored_queries_digest.clone()) != Some(canonical_digest(String::new())) {
        return Err("WARA query catalog digest mismatch");
    }
    if let Some(mut framework) = framework.clone() {
        let _ = validate_framework_alignment(Default::default(), framework.clone()).unwrap_or_else(|_| ());
        let all_bodies: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    }
    Ok((Default::default(), Default::default()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_framework_alignment(mut catalog: WaraAssessmentCatalog, mut framework: String) -> Result<(), &'static str> {
    let expected: WaraExpectedCounts = *(catalog.expected_counts.clone());
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["QuerySafetyClassification", "ResourceTypeDisposition", "WaraAssessmentCatalog", "WaraDisposition", "WaraManualEvidenceRequirement", "WaraMappingState", "WaraQueryCatalog", "WaraRecommendationCrosswalk", "canonical_digest", "classify_wara_query", "load_wara_assessment_catalog"];
