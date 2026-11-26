use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RuleInterface {
    #[default]
    Evaluable,
    Remediable,
}

impl RuleInterface {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Evaluable => "Evaluable",
            Self::Remediable => "Remediable",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SubmissionCriterionKind {
    #[default]
    ResourceTypeRegistered,
    ObjectTypeRegistered,
    PropertyExists,
    LinkExists,
}

impl SubmissionCriterionKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ResourceTypeRegistered => "resource_type_registered",
            Self::ObjectTypeRegistered => "object_type_registered",
            Self::PropertyExists => "property_exists",
            Self::LinkExists => "link_exists",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CheckLogic {
    pub kind: String,
    pub reference: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Remediation {
    pub template_ref: String,
    pub cost_impact_monthly_usd: Option<f64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Provenance {
    pub source_url: String,
    pub source_version: Option<String>,
    pub resolved_ref: String,
    pub content_hash: String,
    pub license: String,
    pub redistribution: String,
    pub retrieved_at: String,
    pub mapped_by: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SubmissionCriterion {
    pub kind: SubmissionCriterionKind,
    pub value: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Rule {
    pub schema_version: String,
    pub id: String,
    pub version: String,
    pub source: String,
    pub severity: String,
    pub category: String,
    pub resource_type: String,
    pub target_object_type: Option<String>,
    pub check_logic: Box<CheckLogic>,
    pub remediation: Box<Remediation>,
    pub remediates: String,
    pub alternatives: Vec<String>,
    pub parameters: BTreeMap<String, String>,
    pub provenance: Box<Provenance>,
    pub applies_to: Vec<String>,
    pub triggered_by: Vec<String>,
    pub evaluates: Vec<String>,
    pub required_interfaces: Vec<RuleInterface>,
    pub submission_criteria: Vec<SubmissionCriterion>,
    pub scope_predicates: BTreeMap<String, String>,
}

impl Rule {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn serialize_rule(&self, mut handler: String) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["CheckLogic", "Provenance", "Remediation", "Rule", "RuleInterface", "SubmissionCriterion", "SubmissionCriterionKind"];
