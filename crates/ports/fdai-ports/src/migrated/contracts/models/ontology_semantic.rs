use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ActionTargetCardinality {
    #[default]
    One,
    Set,
}

impl ActionTargetCardinality {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::One => "one",
            Self::Set => "set",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ActionParameterRedaction {
    #[default]
    Redact,
    AuditSafe,
}

impl ActionParameterRedaction {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Redact => "redact",
            Self::AuditSafe => "audit_safe",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ActionTransactionMode {
    #[default]
    Atomic,
    Saga,
}

impl ActionTransactionMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Atomic => "atomic",
            Self::Saga => "saga",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ActionLockScope {
    #[default]
    Target,
    TargetSet,
}

impl ActionLockScope {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Target => "target",
            Self::TargetSet => "target_set",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ActionSemanticEffectKind {
    #[default]
    InternalWrite,
    CatalogPr,
    ProviderCommand,
    Notification,
    Schedule,
}

impl ActionSemanticEffectKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::InternalWrite => "internal_write",
            Self::CatalogPr => "catalog_pr",
            Self::ProviderCommand => "provider_command",
            Self::Notification => "notification",
            Self::Schedule => "schedule",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ActionPostconditionKind {
    #[default]
    Property,
    Metric,
    Event,
    Function,
}

impl ActionPostconditionKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Property => "property",
            Self::Metric => "metric",
            Self::Event => "event",
            Self::Function => "function",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionTargetSelector {
    pub type_ref: String,
    pub cardinality: ActionTargetCardinality,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionParameterDeclaration {
    pub name: String,
    pub required: bool,
    #[allow(clippy::type_complexity)]
    pub inline_schema: Option<BTreeMap<String, String>>,
    pub schema_ref: Option<String>,
    pub redaction: ActionParameterRedaction,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionReadSetReference {
    pub function_ref: String,
    pub properties: Vec<String>,
    pub max_objects: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionSubmissionCriterion {
    pub criterion_ref: Option<String>,
    pub function_ref: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionEffectSpec {
    pub effect_id: String,
    pub kind: ActionSemanticEffectKind,
    pub operation_ref: String,
    pub rollback_operation_ref: Option<String>,
    pub grants_authority: bool,
}

impl ActionEffectSpec {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.grants_authority { return Err("grants_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionPostconditionSpec {
    pub postcondition_id: String,
    pub kind: ActionPostconditionKind,
    pub observation_ref: Option<String>,
    pub function_ref: Option<String>,
    pub evidence_required: bool,
    pub grants_authority: bool,
}

impl ActionPostconditionSpec {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !self.evidence_required { return Err("evidence_required violated literal bool invariant"); }
        if self.grants_authority { return Err("grants_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionTransactionPolicy {
    pub mode: ActionTransactionMode,
    pub lock_scope: ActionLockScope,
    pub max_affected_objects: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionSemanticContract {
    pub target: Box<ActionTargetSelector>,
    pub parameters: Vec<ActionParameterDeclaration>,
    pub read_sets: Vec<ActionReadSetReference>,
    pub submission_criteria: Vec<ActionSubmissionCriterion>,
    pub planner_ref: String,
    pub effects: Vec<ActionEffectSpec>,
    pub postconditions: Vec<ActionPostconditionSpec>,
    pub transaction_policy: Box<ActionTransactionPolicy>,
}

impl ActionTargetSelector {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn targets_object_or_interface(&self) -> Result<ActionTargetSelector, &'static str> {
        Err("runtime_binding_required")
    }
}

impl ActionParameterDeclaration {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn has_one_typed_schema(&self) -> Result<ActionParameterDeclaration, &'static str> {
        if (self.inline_schema.is_none()) == (self.schema_ref.is_none()) {
            return Err("action parameter MUST declare exactly one of inline_schema or schema_ref");
        }
        if self.inline_schema.is_some() {
            if contains_json_schema_ref(String::new()) {
                return Err("action parameter inline_schema uses schema_ref for declaration reference");
            }
        }
        Ok(self.clone())
    }
}

impl ActionReadSetReference {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn references_function(mut value: String) -> Result<String, &'static str> {
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn properties_are_unique(mut value: Vec<String>) -> Vec<String> {
        let _ = require_unique(String::from("action read-set properties"), String::new()).unwrap_or_else(|_| ());
        value.clone()
    }
}

impl ActionSubmissionCriterion {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn has_one_criterion_reference(&self) -> Result<ActionSubmissionCriterion, &'static str> {
        if (self.criterion_ref.is_none()) == (self.function_ref.is_none()) {
            return Err("action submission criterion MUST declare exactly one criterion_ref or fu");
        }
        Ok(self.clone())
    }
}

impl ActionPostconditionSpec {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn has_exact_observation_reference(&self) -> Result<ActionPostconditionSpec, &'static str> {
        if (self.observation_ref.is_none()) == (self.function_ref.is_none()) {
            return Err("action postcondition MUST declare exactly one observation_ref or functio");
        }
        Ok(self.clone())
    }
}

impl ActionSemanticContract {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn is_bounded_and_unambiguous(&self) -> Result<ActionSemanticContract, &'static str> {
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_unique(mut label: String, mut values: String) -> Result<(), &'static str> {
    if label.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn contains_json_schema_ref(mut value: String) -> bool {
    if value.is_empty() {
        return false;
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["ActionEffectSpec", "ActionLockScope", "ActionParameterDeclaration", "ActionParameterRedaction", "ActionPostconditionKind", "ActionPostconditionSpec", "ActionReadSetReference", "ActionSemanticContract", "ActionSemanticEffectKind", "ActionSubmissionCriterion", "ActionTargetCardinality", "ActionTargetSelector", "ActionTransactionMode", "ActionTransactionPolicy"];
